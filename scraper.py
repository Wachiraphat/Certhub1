import requests
import pymysql
import re
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

# ================= 1. กำหนดค่าเชื่อมต่อ Database RDS =================
RDS_HOST = "YOUR_RDS_HOST"
RDS_USER = "admin"
RDS_PASS = "YOUR_RDS_PASS"
RDS_DB   = "tracker_db"

def get_connection():
    return pymysql.connect(
        host=RDS_HOST,
        user=RDS_USER,
        password=RDS_PASS,
        database=RDS_DB
    )

# ----------------- ส่วนที่ 1: ดึงราคา Voucher ปกติ (GetCertified4Less) -----------------
def scrape_getcertified4less():
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    endpoints = [
        ("https://getcertified4less.com/collections/comptia-vouchers/products.json", "CompTIA"),
        ("https://getcertified4less.com/collections/aws-vouchers/products.json", "AWS Certification"),
        ("https://getcertified4less.com/collections/microsoft-vouchers/products.json", "Microsoft Learn")
    ]
    records = []
    print("[*] กำลังดึงข้อมูลราคา Voucher จาก getcertified4less.com...")

    for url, platform_name in endpoints:
        try:
            res = requests.get(url, headers=headers, timeout=15)
            if res.status_code == 200:
                data = res.json()
                for prod in data.get("products", []):
                    raw_title = prod.get("title", "").strip()
                    handle = prod.get("handle", "")
                    direct_url = f"https://getcertified4less.com/products/{handle}"
                    
                    # ตัด Expires ... ออกจากชื่อ
                    clean_title = re.sub(r'Expires\s+\d{1,2}/\d{1,2}/\d{4}', '', raw_title, flags=re.IGNORECASE).strip()
                    clean_title = clean_title.rstrip('- ').strip()

                    variants = prod.get("variants", [])
                    if variants:
                        price_usd = float(variants[0].get("price", 0.0))
                        compare_at_price_usd = variants[0].get("compare_at_price")
                        current_price = round(price_usd * 35.0, 2)
                        target_price = current_price
                        
                        # กำหนดวันหมดอายุโปรโมชัน SALE
                        if compare_at_price_usd and float(compare_at_price_usd) > price_usd:
                            valid_until = datetime.now() + timedelta(days=7)
                        else:
                            valid_until = datetime.now() + timedelta(days=30)
                        
                        records.append((
                            clean_title[:250],
                            platform_name,
                            direct_url,
                            current_price,
                            target_price,
                            "Monitoring",
                            valid_until
                        ))
        except Exception as e:
            print(f"[!] Error ดึง Voucher จาก {url}: {e}")

    print(f"[+] สกัดข้อมูล Voucher สำเร็จ: {len(records)} รายการ")
    return records

# ----------------- ส่วนที่ 2: ดึงข่าวดีลสอบฟรี 100% (free-certifications.com) -----------------
def scrape_free_certifications_site():
    url = "https://free-certifications.com/"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    free_records = []
    print(f"[*] กำลังดึงข้อมูลสิทธิ์สอบใบเซอร์ฟรีจาก {url}...")

    try:
        res = requests.get(url, headers=headers, timeout=15)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            # ค้นหารายการลิงก์และคอร์ส/สอบฟรีในหน้าเว็บ
            for a_tag in soup.find_all('a', href=True):
                title = a_tag.get_text().strip()
                link = a_tag['href']
                
                # กรองเอาเฉพาะรายการที่เป็นชื่อใบรับรองหรือโครงการที่มีความยาวพอเหมาะ
                if len(title) > 8 and not title.lower().startswith(('home', 'about', 'contact', 'privacy')):
                    # อนุมาน Provider จากข้อความ
                    provider = "Cloud / Security"
                    if "aws" in title.lower(): provider = "AWS"
                    elif "microsoft" in title.lower() or "azure" in title.lower(): provider = "Microsoft"
                    elif "cisco" in title.lower(): provider = "Cisco"
                    elif "oracle" in title.lower(): provider = "Oracle"
                    elif "google" in title.lower(): provider = "Google Cloud"
                    elif "isc2" in title.lower() or "security" in title.lower(): provider = "Cybersecurity"

                    # ปรับลิงก์ให้เป็น absolute url หากเป็น relative path
                    if not link.startswith("http"):
                        link = f"https://free-certifications.com/{link.lstrip('/')}"

                    desc = f"100% Free Certification Exam & Training Initiative provided by {provider}."
                    free_records.append((
                        title[:250],
                        provider[:80],
                        desc[:300],
                        "FREE-100",
                        link,
                        True
                    ))
            print(f"[+] สกัดข้อมูลดีลสอบฟรีได้สำเร็จ: {len(free_records)} รายการ")
    except Exception as e:
        print(f"[!] เกิดข้อผิดพลาดในการดึงข้อมูลจาก free-certifications.com: {e}")

    return free_records

# ----------------- ฟังก์ชันบันทึกข้อมูลลงฐานข้อมูล -----------------
def save_data(courses, free_deals):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            # 1. บันทึก Voucher ปกติ (พร้อมอัปเดต updated_at)
            if courses:
                sql_courses = """
                INSERT INTO courses (name, platform, url, current_price, target_price, status, valid_until, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                ON DUPLICATE KEY UPDATE 
                    name = VALUES(name),
                    current_price = VALUES(current_price),
                    url = VALUES(url),
                    valid_until = VALUES(valid_until),
                    updated_at = NOW();
                """
                cursor.executemany(sql_courses, courses)

            # 2. บันทึกดีลสอบฟรี
            if free_deals:
                cursor.execute("TRUNCATE TABLE free_deals;")  # เคลียร์ข่าวเก่าเพื่อเอาข่าวสดล่าสุด
                sql_free = """
                INSERT INTO free_deals (title, provider, description, code, link, is_exclusive)
                VALUES (%s, %s, %s, %s, %s, %s);
                """
                cursor.executemany(sql_free, free_deals)

            conn.commit()
            print(f"[✅] อัปเดตข้อมูลทั้งหมดลง Amazon RDS เรียบร้อยแล้ว!")
    finally:
        conn.close()

if __name__ == "__main__":
    course_list = scrape_getcertified4less()
    free_list = scrape_free_certifications_site()
    save_data(course_list, free_list)
