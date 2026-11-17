import json
import re
import datetime
from datetime import timedelta
import boto3
import pymysql
import requests
from bs4 import BeautifulSoup

# ======================= ตั้งค่าการเชื่อมต่อ =======================
RDS_HOST = "YOUR_RDS_HOST"
RDS_USER = "admin"
RDS_PASS = "YOUR_RDS_PASS"
RDS_DB   = "tracker_db"

S3_BUCKET_NAME = "S3_BUCKET_NAME"       # ใส่ชื่อ เช่น certhub-logs-xxx-us-east-1-an
SNS_TOPIC_ARN  = "SNS_TOPIC_ARN"     # เช่น arn:aws:sns:us-east-1:xxxxxx:certhub-price-alert
# =================================================================



s3_client = boto3.client('s3')
sns_client = boto3.client('sns')

def get_db_connection():
    return pymysql.connect(
        host=RDS_HOST,
        user=RDS_USER,
        password=RDS_PASS,
        database=RDS_DB,
        cursorclass=pymysql.cursors.DictCursor
    )

# ----------------- ฟังก์ชันดึงข้อมูลสดจากเว็บต้นทาง -----------------
def sync_live_prices(cursor):
    headers = {'User-Agent': 'Mozilla/5.0'}
    endpoints = [
        ("https://getcertified4less.com/collections/comptia-vouchers/products.json", "CompTIA"),
        ("https://getcertified4less.com/collections/aws-vouchers/products.json", "AWS Certification"),
        ("https://getcertified4less.com/collections/microsoft-vouchers/products.json", "Microsoft Learn")
    ]
    alert_logs = []

    for url, platform_name in endpoints:
        try:
            res = requests.get(url, headers=headers, timeout=15)
            if res.status_code != 200:
                continue
            for prod in res.json().get("products", []):
                raw_title = prod.get("title", "").strip()
                handle = prod.get("handle", "")
                direct_url = f"https://getcertified4less.com/products/{handle}"
                clean_title = re.sub(r'Expires\s+\d{1,2}/\d{1,2}/\d{4}', '', raw_title, flags=re.IGNORECASE).strip().rstrip('- ').strip()

                variants = prod.get("variants", [])
                if not variants:
                    continue

                price_usd = float(variants[0].get("price", 0.0))
                compare_usd = variants[0].get("compare_at_price")
                live_price = round(price_usd * 35.0, 2)
                valid_until = datetime.datetime.now() + timedelta(days=7 if (compare_usd and float(compare_usd) > price_usd) else 30)

                cursor.execute("SELECT id, current_price, target_price, status FROM courses WHERE name = %s", (clean_title[:250],))
                existing = cursor.fetchone()

                if existing:
                    target_price = float(existing['target_price'])
                    old_price = float(existing['current_price'])
                    
                    is_discounted = (live_price < target_price) or (compare_usd and float(compare_usd) > price_usd)
                    new_status = 'Discounted' if is_discounted else 'Monitoring'

                    cursor.execute("""
                        UPDATE courses 
                        SET current_price = %s, status = %s, url = %s, valid_until = %s 
                        WHERE id = %s
                    """, (live_price, new_status, direct_url, valid_until, existing['id']))

                    if is_discounted and live_price < old_price:
                        send_alert(clean_title, platform_name, live_price, target_price, direct_url, alert_logs)
                else:
                    cursor.execute("""
                        INSERT INTO courses (name, platform, url, current_price, target_price, status, valid_until)
                        VALUES (%s, %s, %s, %s, %s, 'Monitoring', %s)
                    """, (clean_title[:250], platform_name, direct_url, live_price, live_price, valid_until))
        except Exception as e:
            print(f"[!] Scrape Error ({url}): {e}")

    try:
        res_free = requests.get("https://free-certifications.com/", headers=headers, timeout=15)
        if res_free.status_code == 200:
            soup = BeautifulSoup(res_free.text, 'html.parser')
            free_records = []
            for a_tag in soup.find_all('a', href=True):
                title = a_tag.get_text().strip()
                link = a_tag['href']
                if len(title) > 8 and not title.lower().startswith(('home', 'about', 'contact', 'privacy')):
                    provider = "AWS" if "aws" in title.lower() else ("Microsoft" if "microsoft" in title.lower() or "azure" in title.lower() else "Cloud / Security")
                    if not link.startswith("http"):
                        link = f"https://free-certifications.com/{link.lstrip('/')}"
                    free_records.append((title[:250], provider, f"100% Free Certification Initiative ({provider})", "FREE-100", link, True))
            if free_records:
                cursor.execute("TRUNCATE TABLE free_deals;")
                cursor.executemany("INSERT INTO free_deals (title, provider, description, code, link, is_exclusive) VALUES (%s, %s, %s, %s, %s, %s)", free_records)
    except Exception as e:
        print(f"[!] Free Deals Scrape Error: {e}")

    return alert_logs

def send_alert(name, platform, new_price, target_price, url, alert_logs):
    message = (
        f"🔥 แจ้งเตือนเวาเชอร์ลดราคาจาก CertHub!\n\n"
        f"ใบเซอร์: {name} ({platform})\n"
        f"ราคาลดเหลือ: {new_price:,.2f} บาท (ราคาเป้าหมาย: {target_price:,.2f} บาท)\n"
        f"ลิงก์สมัครสอบ: {url}\n"
        f"เวลาที่ตรวจสอบ: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    sns_client.publish(TopicArn=SNS_TOPIC_ARN, Subject=f"⚡ ลดราคาแล้ว: {name}", Message=message)
    alert_logs.append({"name": name, "new_price": new_price, "target_price": target_price, "status": "Alert Sent"})

# ----------------- Main Handler -----------------
def lambda_handler(event, context):
    connection = get_db_connection()
    alert_logs = []
    try:
        with connection.cursor() as cursor:
            if event.get("test_mode"):
                discount_pct = float(event.get("discount_percent", 40))
                cursor.execute("SELECT * FROM courses WHERE status = 'Monitoring' LIMIT 1")
                course = cursor.fetchone()
                if course:
                    target_price = float(course['target_price'])
                    new_price = round(target_price * (1 - discount_pct / 100.0), 2)
                    cursor.execute("UPDATE courses SET current_price = %s, status = 'Discounted' WHERE id = %s", (new_price, course['id']))
                    send_alert(course['name'], course['platform'], new_price, target_price, course['url'], alert_logs)
            else:
                alert_logs = sync_live_prices(cursor)

        connection.commit()

        if alert_logs:
            timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            s3_client.put_object(
                Bucket=S3_BUCKET_NAME,
                Key=f"history/price_drop_{timestamp}.json",
                Body=json.dumps(alert_logs, ensure_ascii=False, indent=2),
                ContentType='application/json'
            )

        return {'statusCode': 200, 'body': json.dumps({'message': 'Sync & Price Check Completed', 'alerts_sent': len(alert_logs)})}
    finally:
        connection.close()
