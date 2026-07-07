import boto3
import os
from dotenv import load_dotenv

load_dotenv()

BUCKET_NAME = os.getenv('R2_BUCKET_NAME')

# Same Cloudflare R2 config the bot uses in kpics_class._setup_s3, exposed as a small
# reusable helper for the API/ingest path. A fresh client per call keeps this stateless;
# the volume here is low enough that pooling isn't worth the complexity.
def get_s3_client():
    return boto3.client(
        service_name='s3',
        endpoint_url=os.getenv('R2_ENDPOINT_URL'),
        aws_access_key_id=os.getenv('R2_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('R2_SECRET_ACCESS_KEY'),
        region_name="auto",
    )

def upload_bytes(key, data, content_type=None):
    try:
        s3 = get_s3_client()
        extra = {"ContentType": content_type} if content_type else {}
        s3.put_object(Bucket=BUCKET_NAME, Key=key, Body=data, **extra)
        return True

    except Exception as e:
        print(f"Error uploading {key} to R2: {e}.")
        return False

def delete_object(key):
    try:
        s3 = get_s3_client()
        s3.delete_object(Bucket=BUCKET_NAME, Key=key)
        return True

    except Exception as e:
        print(f"Error deleting {key} from R2: {e}.")
        return False

def copy_object(src_key, dst_key):
    # Server-side copy within the bucket (used to promote analysis -> approved on approval).
    try:
        s3 = get_s3_client()
        s3.copy_object(Bucket=BUCKET_NAME, CopySource={"Bucket": BUCKET_NAME, "Key": src_key}, Key=dst_key)
        return True

    except Exception as e:
        print(f"Error copying {src_key} -> {dst_key} in R2: {e}.")
        return False

def get_object_bytes(key):
    # Fetch the raw bytes of one object (used to stream a pending photo to the approval webapp).
    try:
        s3 = get_s3_client()
        response = s3.get_object(Bucket=BUCKET_NAME, Key=key)
        return response["Body"].read()

    except Exception as e:
        print(f"Error reading {key} from R2: {e}.")
        return None
