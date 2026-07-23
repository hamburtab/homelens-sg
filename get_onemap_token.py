import requests
import os

url = "https://www.onemap.gov.sg/api/auth/post/getToken"

payload = {
    "email": os.environ["ONEMAP_EMAIL"],
    "password": os.environ["ONEMAP_PASSWORD"],
}

response = requests.post(url, json=payload, timeout=30)

print(response.status_code)
print(response.text)
