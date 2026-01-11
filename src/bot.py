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

def main():
    # PHASE 1 - Initialization - Setup
    try:
        # Cloudflare R2 / Boto3 setup
        s3 = boto3.client(
            service_name='s3',
            endpoint_url= os.getenv('R2_ENDPOINT_URL'),
            aws_access_key_id = os.getenv('R2_ACCESS_KEY_ID'),
            aws_secret_access_key = os.getenv('R2_SECRET_ACCESS_KEY'),
            region_name="auto",
        )

        # Twitter API setup
        twitter_auth = tweepy.OAuth1UserHandler(
            os.getenv('TWITTER_API_KEY'),
            os.getenv('TWITTER_API_KEY_SECRET'),
            os.getenv('TWITTER_ACCESS_TOKEN'),
            os.getenv('TWITTER_ACCESS_TOKEN_SECRET')
        )

        api_v1 = tweepy.API(twitter_auth)

        client_v2 = tweepy.Client(
            consumer_key=os.getenv('TWITTER_API_KEY'),
            consumer_secret=os.getenv('TWITTER_API_KEY_SECRET'),
            access_token=os.getenv('TWITTER_ACCESS_TOKEN'),
            access_token_secret=os.getenv('TWITTER_ACCESS_TOKEN_SECRET')
        )

        print("Connections estabilished successfully.")

    except Exception as e:
        print(f"Error setting up Cloudflare R2 or Twitter API: {e}")
        return
        
    # 2. Search and download boto3 image after Cloudflare R2 and Twitter API setup
    try:
        search_answer = s3.list_objects_v2(Bucket=BUCKET_NAME)

        if 'Contents' not in search_answer:
            print("Bucket is empty or does not exist.")
            return

        print(f"Connected to Cloudflare R2 successfully, {search_answer}.")

        idols_list = []
        for obj in search_answer['Contents']:
            data = process_data(obj['Key'])
            if data:
                data['last_modified'] = obj['LastModified']
                idols_list.append(data)

        if not idols_list or idols_list[0] is None:
            print("No valid image files found in the bucket.")
            return
        
        idols_list.sort(key=priority_sort, reverse=True)
        file_name = idols_list[0]

        object = s3.get_object(Bucket=BUCKET_NAME, Key=file_name['key'])
        image_data = object['Body'].read()
        print(f"Image {file_name['key']} downloaded successfully from R2.")

    except Exception as e:
        print(f"Error connecting to Cloudflare R2: {e}")
        return

    # 3. Twitter media upload
    try:
        post_date = get_current_date()

        media = api_v1.media_upload(filename=file_name['key'], file=io.BytesIO(image_data))

        client_v2.create_tweet(text=file_name['text'], media_ids=[media.media_id])

        print(f"Tweet posted successfully for {file_name['key']}. At {post_date}, ID: {media.media_id}")

        s3.delete_object(Bucket=BUCKET_NAME, Key=file_name['key'])
        print(f"Image {file_name['key']} deleted successfully from R2 after tweeting.")

    except Exception as e:
        print(f"Error posting tweet: {e}")

if __name__ == "__main__":
    main()