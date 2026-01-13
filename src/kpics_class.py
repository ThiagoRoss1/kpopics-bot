import boto3
import tweepy
from dotenv import load_dotenv
import io
import os
from utils.processor import process_data
from utils.sorter import priority_sort
from datetime import datetime
from zoneinfo import ZoneInfo

load_dotenv()

BUCKET_NAME = os.getenv('R2_BUCKET_NAME')
TIMEZONE_BRT = ZoneInfo("America/Sao_Paulo")

def get_current_date():
    now = datetime.now(TIMEZONE_BRT).replace(microsecond=0)
    return now.strftime("%d/%m/%Y %H:%M:%S")

class KpopBot:
    def __init__(self, idol_prefix):
        self.idol_prefix = idol_prefix

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
        
        file_name = self._get_image()
        if file_name and self.image_data:
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

            idols_list = []
            for obj in search_answer['Contents']:
                data = process_data(obj['Key'])

                if data:
                    # future test (multiple bots): filter by idol prefix
                    # is_general = self.idol_prefix == "GENERAL"
                    # is_match = self.idol_prefix.lower() in data['key'].lower()

                    # if is_general or is_match:
                    #     .... same as below ....
                    data['last_modified'] = obj['LastModified']
                    idols_list.append(data)
            
            if not idols_list or idols_list[0] is None:
                print("No valid image files found in the bucket.")
                return None
            
            idols_list.sort(key=priority_sort, reverse=True)
            file_name = idols_list[0]

            object = self.s3.get_object(Bucket=BUCKET_NAME, Key=file_name['key'])
            self.image_data = object['Body'].read()
            print(f"Image {file_name['key']} downloaded successfully from R2.")
            self.file_name = file_name
            return file_name
        
        except Exception as e:
            print(f"Error connecting to Cloudflare R2: {e}")
            return None

    def _upload_media(self):
        try:
            post_date = get_current_date()
            media = self.api_v1.media_upload(
                filename=self.file_name['key'], 
                file=io.BytesIO(self.image_data)
            )

            self.client_v2.create_tweet(
                text=self.file_name['text'],
                media_ids=[media.media_id]
            )

            print(f"Tweet posted successfully for {self.idol_prefix} of filename -> {self.file_name['key']}, At {post_date}, ID: {media.media_id}")
            self.s3.delete_object(
                Bucket=BUCKET_NAME,
                Key=self.file_name['key']
            )

            print(f"Image {self.file_name['key']} deleted successfully from R2 after tweeting.")

            # print("Bot simulation")
            # print(f"Idol bot: {self.idol_prefix}")
            # print(f"File name: {self.file_name['key']}")
            # print(f"Text tweet: {self.file_name['text']}")
            # print(f"Post date: {post_date}")
            # print(f"Would delete image {self.file_name['key']} from R2 after tweeting.")
            # print(f"Simulation complete for {self.idol_prefix} bot.")
            # print(f"----------------------------------")

        except Exception as e:
            print(f"Error posting tweet: {e}")