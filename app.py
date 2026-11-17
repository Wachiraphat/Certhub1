from flask import Flask, render_template, jsonify, request
import pymysql

app = Flask(__name__)

# กำหนดค่าเชื่อมต่อ Database RDS
RDS_HOST = "YOUR_RDS_HOST"
RDS_USER = "admin"
RDS_PASS = "YOUR_RDS_PASS"
RDS_DB   = "tracker_db"

def get_db_connection():
    return pymysql.connect(
        host=RDS_HOST,
        user=RDS_USER,
        password=RDS_PASS,
        database=RDS_DB,
        cursorclass=pymysql.cursors.DictCursor
    )

# ----------------- 1. หน้าแรก Dashboard -----------------
@app.route('/')
def index():
    courses = []
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM courses ORDER BY id ASC;")
            courses = cursor.fetchall()
        conn.close()
    except Exception as e:
        print(f"Database error: {e}")
    return render_template('index.html', courses=courses)

# ----------------- 2. Level 5: API สำหรับกระดิ่งแจ้งเตือน (Notifications) -----------------
@app.route('/api/notifications')
def get_notifications():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT id, name, platform, current_price, target_price 
                FROM courses 
                WHERE status = 'Discounted' OR current_price < target_price
                ORDER BY id DESC LIMIT 5;
            """)
            alerts = cursor.fetchall()
            return jsonify({'success': True, 'notifications': alerts})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        conn.close()

# ----------------- 3. Level 5: API ตรวจสอบสถานะการ Subscribe -----------------
@app.route('/api/subscription/status')
def subscription_status():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT status FROM subscribers WHERE email = 'demo@certhub.local';")
            user = cursor.fetchone()
            is_subscribed = bool(user and user.get('status') == 'Subscribed')
            return jsonify({'is_subscribed': is_subscribed})
    except Exception as e:
        return jsonify({'is_subscribed': False, 'error': str(e)}), 500
    finally:
        conn.close()

# ----------------- 4. Level 5: API จำลองการจ่ายเงิน $1 เพื่อปลดล็อก -----------------
@app.route('/api/subscribe', methods=['POST'])
def process_subscription():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE subscribers 
                SET status = 'Subscribed', amount_paid = 1.00, subscribed_at = NOW() 
                WHERE email = 'demo@certhub.local';
            """)
            conn.commit()
            return jsonify({'success': True, 'message': 'Subscribed successfully for $1.00!'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        conn.close()

# ----------------- 5. Level 5: API ยกเลิก Subscription -----------------
@app.route('/api/unsubscribe', methods=['POST'])
def process_unsubscription():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE subscribers 
                SET status = 'Free', amount_paid = 0.00, subscribed_at = NULL 
                WHERE email = 'demo@certhub.local';
            """)
            conn.commit()
            return jsonify({'success': True, 'message': 'Subscription cancelled successfully!'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        conn.close()

# ----------------- 6. Level 5: API ดึงข่าวสอบใบเซอร์ฟรี 100% -----------------
@app.route('/api/free-vouchers')
def get_free_vouchers():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT status FROM subscribers WHERE email = 'demo@certhub.local';")
            user = cursor.fetchone()
            is_subscribed = bool(user and user.get('status') == 'Subscribed')

            if not is_subscribed:
                return jsonify({
                    'locked': True,
                    'message': 'Unlock Free Exam Vouchers for only $1.00/month!'
                }), 403

            cursor.execute("SELECT * FROM free_deals ORDER BY id DESC LIMIT 20;")
            deals = cursor.fetchall()
            return jsonify({'locked': False, 'deals': deals})
    except Exception as e:
        return jsonify({'locked': True, 'error': str(e)}), 500
    finally:
        conn.close()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
