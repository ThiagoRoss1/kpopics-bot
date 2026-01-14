import boto3
import tweepy
from dotenv import load_dotenv
import io
import os
from utils.processor import process_data
from utils.sorter import priority_sort
from utils.database_operations import log_posted_image, get_log_history, get_last_posted_image
from datetime import datetime
from zoneinfo import ZoneInfo

load_dotenv()

BUCKET_NAME = os.getenv('R2_BUCKET_NAME')
TIMEZONE_BRT = ZoneInfo("America/Sao_Paulo")

def get_current_date():
    now = datetime.now(TIMEZONE_BRT).replace(microsecond=0)
    return now.strftime("%d/%m/%Y %H:%M:%S")

class KpopBot:
    def __init__(self, idol_prefix, active_bots):
        self.idol_prefix = idol_prefix
        self.active_bots = active_bots

        # Initialize connections
        self.s3 = None
        self.api_v1 = None
        self.client_v2 = None
        self.image_data = None
        self.file_name = None

    # Running the bot
    def run(self):
        self._setup_s3()
        self._setup_twitter()

        if not self.s3 or not self.api_v1 or not self.client_v2:
            print(f"Setup incomplete for {self.idol_prefix}. Exiting.")
            return
        
        self._upload_media()   
                
    # PHASE 1 - Initialization - Setup
    # Cloudflare R2 / Boto3 setup
    def _setup_s3(self):
        try:
            self.s3 = boto3.client(
                service_name='s3',
                endpoint_url= os.getenv('R2_ENDPOINT_URL'),
                aws_access_key_id=os.getenv('R2_ACCESS_KEY_ID'),
                aws_secret_access_key=os.getenv('R2_SECRET_ACCESS_KEY'),
                region_name="auto",
            )

            print("Cloudflare R2 set up successfully.")
        
        except Exception as e:
            print(f"Error setting up Cloudflare R2: {e}")
            self.s3 = None
        
    # Twitter API setup
    def _setup_twitter(self):
        try:
            twitter_auth = tweepy.OAuth1UserHandler(
                os.getenv(f'{self.idol_prefix}_TWITTER_API_KEY'),
                os.getenv(f'{self.idol_prefix}_TWITTER_API_KEY_SECRET'),
                os.getenv(f'{self.idol_prefix}_TWITTER_ACCESS_TOKEN'),
                os.getenv(f'{self.idol_prefix}_TWITTER_ACCESS_TOKEN_SECRET')
            )
            self.api_v1 = tweepy.API(twitter_auth)

            self.client_v2 = tweepy.Client(
                consumer_key=os.getenv(f'{self.idol_prefix}_TWITTER_API_KEY'),
                consumer_secret=os.getenv(f'{self.idol_prefix}_TWITTER_API_KEY_SECRET'),
                access_token=os.getenv(f'{self.idol_prefix}_TWITTER_ACCESS_TOKEN'),
                access_token_secret=os.getenv(f'{self.idol_prefix}_TWITTER_ACCESS_TOKEN_SECRET')
            )

            print(f"Twitter API for {self.idol_prefix} set up successfully.")

        except Exception as e:
            print(f"Error setting up Twitter API for {self.idol_prefix}: {e}")
            self.api_v1 = None
            self.client_v2 = None

    # PHASE 2 - Search and download boto3 image after Cloudflare R2 and Twitter API setup
    def _get_image(self):
        try:
            search_answer = self.s3.list_objects_v2(Bucket=BUCKET_NAME)

            if 'Contents' not in search_answer:
                print("Bucket is empty or does not exist.")
                return None
            
            print(f"Connected to Cloudflare R2 successfully, {search_answer}.") # remove search_answer after testing

            self.idols_list = []
            for obj in search_answer['Contents']:
                data = process_data(obj['Key'])

                if data:
                    # future test (multiple bots): filter by idol prefix
                    is_general = self.idol_prefix == "GENERAL"
                    is_match = self.idol_prefix.lower() in data['key'].lower()

                    if is_general or is_match:
                        data['last_modified'] = obj['LastModified']
                        self.idols_list.append(data)
            
            if not self.idols_list or self.idols_list[0] is None:
                print("No valid image files found in the bucket.")
                return None
            
            self.idols_list.sort(key=priority_sort, reverse=True)

            last_post = get_last_posted_image(self.idol_prefix)
            file_name = None
            
            for file in self.idols_list:
                history = get_log_history(file['key'])
                if self.idol_prefix in history:
                    continue

                if self.idol_prefix == "GENERAL":

                    current_idol = ", ".join(file['idols']) if isinstance(file['idols'], list) else file['idols']
                    if last_post and last_post['last_idol'] == current_idol:
                        print(f"Skipping file {file['key']} -> posted this photo recently with GENERAL bot.")
                        continue

                file_name = file
                break

            if not file_name:
                print("No new images to post found for this bot.")
                return None
            
            if file_name['combo']:
                post_pack = [file for file in self.idols_list
                             if file.get('idols') == file_name.get('idols')
                             and file.get('date') == file_name.get('date')
                             and file.get('combo') == file_name.get('combo')]
                
                return sorted(post_pack, key=lambda x: int(x['copies']))[:4]

            return [file_name]
        
        except Exception as e:
            print(f"Error connecting to Cloudflare R2: {e}")
            return None
        
    def _download_image(self):
        post_pack = self._get_image()

        if not post_pack:
            return None
        
        media_data = []

        try:
            for filename in post_pack:
                print(f"Downloading image {filename['key']}...")
                response_object = self.s3.get_object(Bucket=BUCKET_NAME, Key=filename['key'])
                image_data = response_object['Body'].read()
                print(f"Image {filename['key']} downloaded successfully from R2.")
                media_data.append((filename, image_data))
            
            return media_data
    
        except Exception as e:
            print(f"Error downloading images from Cloudflare R2: {e}")
            return None

    def _upload_media(self):
        media_data = self._download_image()
        
        if not media_data:
            return None
        
        media_ids = []
            
        try:
            for filename, image_data in media_data:
                post_date = get_current_date()
                media = self.api_v1.media_upload(
                    filename=filename['key'], 
                    file=io.BytesIO(image_data)
                )
                media_ids.append(media.media_id)

            first_file = media_data[0][0]

            tweet = self.client_v2.create_tweet(
                text=first_file['text'],
                media_ids=media_ids  
            )

            if tweet:
                print(f"Tweet posted successfully for {self.idol_prefix} of filename(s) -> {[file['key'] for file, _ in media_data]}, At {post_date}, ID: {media.media_id}")

                for filename, _ in media_data:
                    idols_string = ", ".join(filename['idols']) if isinstance(filename['idols'], list) else filename['idols']

                    log_posted_image(
                        file_key=filename['key'],
                        bot_name=self.idol_prefix,
                        last_idol=idols_string
                    )

                    idols_list = filename['idols'] if isinstance(filename['idols'], list) else [filename['idols']]

                    potential_bots = ["GENERAL"] + [idol.upper() for idol in idols_list]
                    needed_bots = [bot for bot in potential_bots if bot in self.active_bots]

                    history = get_log_history(filename['key'])

                    if all(bot in history for bot in needed_bots):
                        
                        self.s3.delete_object(
                            Bucket=BUCKET_NAME,
                            Key=filename['key']
                        )

                        print(f"Image {filename['key']} deleted successfully from R2 after tweeting.")
                    
                    else:
                        missing = [bot for bot in needed_bots if bot not in history]
                        print(f"Image {filename['key']} not deleted yet. Missing bot(s): {missing}.")

            # print("Bot simulation")
            # print(f"Idol bot: {self.idol_prefix}")
            # print(f"Idol name: {first_file['idols']}")
            # print(f"File name: {[file['key'] for file, _ in media_data]}")
            # print(f"Text tweet: \n{first_file['text']}")
            # print(f"Post date: {post_date}")
            # print(f"Media IDs: {media_ids}")
            # print(f"Image data: {[len(image_data) for _, image_data in media_data]} bytes")
            # print(f"Would log posted image(s) for {[file['key'] for file, _ in media_data]} under bot {self.idol_prefix}.")
            # print(f"Would delete image {[filename['key'] for filename, _ in media_data]} from R2 after tweeting.")
            # print(f"Simulation complete for {self.idol_prefix} bot.")
            # print(f"----------------------------------")

        except Exception as e:
            print(f"Error posting tweet: {e}")


# Prior code 

# response_object = self.s3.get_object(Bucket=BUCKET_NAME, Key=file_name['key'])
# self.image_data = response_object['Body'].read()
# print(f"Image {file_name['key']} downloaded successfully from R2.")
# self.file_name = file_name
# return file_name

# file_name = self.idols_list[0]