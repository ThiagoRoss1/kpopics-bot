import boto3
import tweepy
from dotenv import load_dotenv
import io
import os

load_dotenv()

BUCKET_NAME = os.getenv('R2_BUCKET_NAME')

# Cloudfare R2 / Boto3 setup
s3 = boto3.client(
    service_name='s3',
    endpoint_url= os.getenv('R2_ENDPOINT_URL'),
    aws_access_key_id = os.getenv('R2_ACCESS_KEY_ID'),
    aws_secret_access_key = os.getenv('R2_SECRET_ACCESS_KEY'),
    region_name="auto",
)

def main():
    # Search and download boto3 image and Twitter API setup
    try:
        search_answer = s3.list_objects_v2(Bucket=BUCKET_NAME, MaxKeys=1)

        if 'Contents' not in search_answer:
            print("Bucket is empty or does not exist.")

        print(f"Connected to Cloudflare R2 successfully, {search_answer}.")

        file_name = search_answer['Contents'][0]['Key']
        object = s3.get_object(Bucket=BUCKET_NAME, Key=file_name)
        image_data = object['Body'].read()
        print(f"Image {file_name} downloaded successfully from R2.")

    except Exception as e:
        print(f"Error connecting to Cloudfare R2: {e}")

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

    # Twitter media upload
    try:
        media = api_v1.media_upload(filename=file_name, file=io.BytesIO(image_data))

        client_v2.create_tweet(text="📸", media_ids=[media.media_id])

        print(f"Tweet {media.media_id} posted successfully.")

        s3.delete_object(Bucket=BUCKET_NAME, Key=file_name)
        print(f"Image {file_name} deleted successfully from R2 after tweeting.")

    except Exception as e:
        print(f"Error posting tweet: {e}")

if __name__ == "__main__":
    main()

