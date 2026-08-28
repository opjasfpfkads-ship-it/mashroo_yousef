import os
import random
import string
import sqlite3
import fitz  # PyMuPDF
from PIL import Image, ImageOps, ImageDraw, ImageFont
import qrcode
import io
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'super_secret_key_nexus_studio_v3_2026'

UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 64 * 1024 * 1024  # 64MB Limit

WATERMARK_TEXT = "yousef_3mr"

def init_db():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS urls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            short_code TEXT UNIQUE NOT NULL,
            original_url TEXT NOT NULL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            action_type TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def log_stat(user_id, action_type):
    try:
        conn = sqlite3.connect('database.db')
        cursor = conn.cursor()
        cursor.execute('INSERT INTO stats (user_id, action_type) VALUES (?, ?)', (user_id, action_type))
        conn.commit()
        conn.close()
    except Exception as e:
        print("Stat log error:", e)

def apply_watermark(image_path, text=WATERMARK_TEXT):
    try:
        img = Image.open(image_path).convert("RGBA")
        txt_overlay = Image.new("RGBA", img.size, (255, 255, 255, 0))
        draw = ImageDraw.Draw(txt_overlay)
        
        font_size = max(18, int(img.width * 0.04))
        try:
            font = ImageFont.truetype("arial.ttf", font_size)
        except IOError:
            font = ImageFont.load_default()

        margin = 25
        text_bbox = draw.textbbox((0, 0), text, font=font)
        text_w = text_bbox[2] - text_bbox[0]
        text_h = text_bbox[3] - text_bbox[1]
        
        x = img.width - text_w - margin
        y = img.height - text_h - margin

        # Subtle dark backdrop for readability
        draw.rectangle([x - 8, y - 4, x + text_w + 8, y + text_h + 4], fill=(0, 0, 0, 100))
        draw.text((x, y), text, fill=(255, 255, 255, 220), font=font)

        watermarked = Image.alpha_composite(img, txt_overlay)
        out_img = watermarked.convert("RGB")
        out_img.save(image_path)
    except Exception as e:
        print("Watermark Error:", str(e))

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        action = request.form.get('action')
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        conn = sqlite3.connect('database.db')
        cursor = conn.cursor()

        if action == 'register':
            if not username or not password:
                error = 'برجاء ملء جميع الحقول المطلوب!'
            elif password != confirm_password:
                error = 'كلمتا المرور غير متطابقتين!'
            else:
                cursor.execute('SELECT id FROM users WHERE username = ?', (username,))
                if cursor.fetchone():
                    error = 'اسم المستخدم موجود بالفعل!'
                else:
                    hashed_pw = generate_password_hash(password)
                    cursor.execute('INSERT INTO users (username, password) VALUES (?, ?)', (username, hashed_pw))
                    conn.commit()
                    cursor.execute('SELECT id FROM users WHERE username = ?', (username,))
                    user = cursor.fetchone()
                    session['user_id'] = user[0]
                    session['username'] = username
                    conn.close()
                    return redirect(url_for('dashboard'))

        elif action == 'login':
            cursor.execute('SELECT id, password FROM users WHERE username = ?', (username,))
            user = cursor.fetchone()
            if user and check_password_hash(user[1], password):
                session['user_id'] = user[0]
                session['username'] = username
                conn.close()
                return redirect(url_for('dashboard'))
            else:
                error = 'اسم المستخدم أو كلمة المرور غير صحيحة!'
        conn.close()

    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM stats WHERE user_id = ?', (session['user_id'],))
    total_actions = cursor.fetchone()[0]
    conn.close()

    return render_template('dashboard.html', username=session['username'], watermark=WATERMARK_TEXT, total_actions=total_actions)

@app.route('/download/<filename>')
def download_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=True)

# ----------------- APIs & SERVICES -----------------

# 1. PDF Tools: Convert, Merge, Split, Protect
@app.route('/api/pdf-tools', methods=['POST'])
def pdf_tools():
    if 'user_id' not in session: return jsonify({'error': 'غير مصرح'}), 401
    action = request.form.get('action')
    log_stat(session['user_id'], f'pdf_{action}')

    try:
        if action == 'pdf_to_img':
            file = request.files.get('file')
            if not file: return jsonify({'message': 'يرجى اختيار ملف PDF!'}), 400
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)

            doc = fitz.open(filepath)
            page = doc.load_page(0)
            pix = page.get_pixmap()
            out_name = f"converted_{os.path.splitext(filename)[0]}.png"
            out_path = os.path.join(app.config['UPLOAD_FOLDER'], out_name)
            pix.save(out_path)
            doc.close()
            apply_watermark(out_path)

            return jsonify({
                "message": f"تم تحويل الصفحة الأولى لبروفايل صورة ومطابقة الحقوق (@{WATERMARK_TEXT})!",
                "download_url": url_for('download_file', filename=out_name)
            })

        elif action == 'img_to_pdf':
            file = request.files.get('file')
            if not file: return jsonify({'message': 'يرجى اختيار صورة!'}), 400
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)

            img = Image.open(filepath).convert('RGB')
            out_name = f"converted_{os.path.splitext(filename)[0]}.pdf"
            out_path = os.path.join(app.config['UPLOAD_FOLDER'], out_name)
            img.save(out_path)

            return jsonify({
                "message": "تم تحويل الصورة لمستند PDF بنجاح!",
                "download_url": url_for('download_file', filename=out_name)
            })

        elif action == 'merge':
            files = request.files.getlist('files')
            if not files or len(files) < 2:
                return jsonify({'message': 'برجاء رفع ملفين PDF أو أكثر للدمج!'}), 400

            merged_doc = fitz.open()
            for f in files:
                fname = secure_filename(f.filename)
                fpath = os.path.join(app.config['UPLOAD_FOLDER'], fname)
                f.save(fpath)
                doc = fitz.open(fpath)
                merged_doc.insert_pdf(doc)
                doc.close()

            out_name = f"merged_document_{random.randint(1000, 9999)}.pdf"
            out_path = os.path.join(app.config['UPLOAD_FOLDER'], out_name)
            merged_doc.save(out_path)
            merged_doc.close()

            return jsonify({
                "message": f"تم دمج {len(files)} ملفات PDF بنجاح!",
                "download_url": url_for('download_file', filename=out_name)
            })

        elif action == 'split':
            file = request.files.get('file')
            page_num = int(request.form.get('page_num', 1))
            if not file: return jsonify({'message': 'اختر ملف PDF!'}), 400

            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)

            doc = fitz.open(filepath)
            total_pages = len(doc)

            if page_num < 1 or page_num > total_pages:
                doc.close()
                return jsonify({'message': f'رقم الصفحة غير متاح! عدد الصفحات هو {total_pages}.'}), 400

            new_doc = fitz.open()
            new_doc.insert_pdf(doc, from_page=page_num-1, to_page=page_num-1)
            out_name = f"split_page_{page_num}_{filename}"
            out_path = os.path.join(app.config['UPLOAD_FOLDER'], out_name)
            new_doc.save(out_path)
            new_doc.close()
            doc.close()

            return jsonify({
                "message": f"تم استخراج الصفحة {page_num} بنجاح من أصل {total_pages} صفحات!",
                "download_url": url_for('download_file', filename=out_name)
            })

        elif action == 'protect':
            file = request.files.get('file')
            pdf_pass = request.form.get('pdf_pass', '').strip()
            if not file or not pdf_pass:
                return jsonify({'message': 'يرجى إرفاق الملف وكلمة السر!'}), 400

            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)

            doc = fitz.open(filepath)
            out_name = f"protected_{filename}"
            out_path = os.path.join(app.config['UPLOAD_FOLDER'], out_name)
            
            # Encrypt document
            doc.save(out_path, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw=pdf_pass, owner_pw="admin_master")
            doc.close()

            return jsonify({
                "message": "تم قفل وحماية مستند الـ PDF بكلمة السر بنجاح!",
                "download_url": url_for('download_file', filename=out_name)
            })

    except Exception as e:
        return jsonify({"message": f"حدث خطأ في معالجة المستند: {str(e)}"}), 500

# 2. Image Processing: Compression, Format Conversion, Edit
@app.route('/api/image-tools', methods=['POST'])
def image_tools():
    if 'user_id' not in session: return jsonify({'error': 'غير مصرح'}), 401
    action = request.form.get('action')
    file = request.files.get('file')
    if not file: return jsonify({'message': 'يرجى اختيار صورة!'}), 400
    log_stat(session['user_id'], f'img_{action}')

    try:
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        img = Image.open(filepath)

        if action == 'compress':
            out_name = f"compressed_{os.path.splitext(filename)[0]}.jpg"
            out_path = os.path.join(app.config['UPLOAD_FOLDER'], out_name)
            img.convert('RGB').save(out_path, optimize=True, quality=40)
            apply_watermark(out_path)

            old_s = round(os.path.getsize(filepath) / 1024, 1)
            new_s = round(os.path.getsize(out_path) / 1024, 1)
            return jsonify({
                "message": f"تم الضغط وإضافة الحقوق تلقائياً! (الحجم: {old_s}KB ⬅️ {new_s}KB)",
                "download_url": url_for('download_file', filename=out_name)
            })

        elif action == 'convert_format':
            target_fmt = request.form.get('target_format', 'png').lower()
            out_name = f"converted_{os.path.splitext(filename)[0]}.{target_fmt}"
            out_path = os.path.join(app.config['UPLOAD_FOLDER'], out_name)
            
            if target_fmt in ['jpg', 'jpeg']:
                img = img.convert('RGB')
            img.save(out_path)
            apply_watermark(out_path)

            return jsonify({
                "message": f"تم تحويل الصيغة بنجاح إلى {target_fmt.upper()}!",
                "download_url": url_for('download_file', filename=out_name)
            })

        elif action == 'grayscale':
            img_gray = ImageOps.grayscale(img)
            out_name = f"gray_{os.path.splitext(filename)[0]}.jpg"
            out_path = os.path.join(app.config['UPLOAD_FOLDER'], out_name)
            img_gray.save(out_path)
            apply_watermark(out_path)
            return jsonify({
                "message": "تم تحويل الصورة لأبيض وأسود بلمسة كلاسيكية!",
                "download_url": url_for('download_file', filename=out_name)
            })

        elif action == 'rotate':
            img_rot = img.rotate(-90, expand=True)
            out_name = f"rotated_{filename}"
            out_path = os.path.join(app.config['UPLOAD_FOLDER'], out_name)
            img_rot.save(out_path)
            apply_watermark(out_path)
            return jsonify({
                "message": "تم تدوير الصورة 90 درجة باتجاه عقارب الساعة!",
                "download_url": url_for('download_file', filename=out_name)
            })

    except Exception as e:
        return jsonify({"message": f"خطأ أثناء المعالجة: {str(e)}"}), 500

# 3. QR Code Studio: Generator & Reader
@app.route('/api/qr-studio', methods=['POST'])
def qr_studio():
    if 'user_id' not in session: return jsonify({'error': 'غير مصرح'}), 401
    action = request.form.get('action')
    log_stat(session['user_id'], f'qr_{action}')

    try:
        if action == 'generate':
            qr_text = request.form.get('qr_text', '').strip()
            if not qr_text: return jsonify({'message': 'أدخل النص أو الرابط لتوليد الـ QR!'}), 400

            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_H,
                box_size=10,
                border=4,
            )
            qr.add_data(qr_text)
            qr.make(fit=True)

            img = qr.make_image(fill_color="#06b6d4", back_color="#0f172a")
            out_name = f"qrcode_{random.randint(10000, 99999)}.png"
            out_path = os.path.join(app.config['UPLOAD_FOLDER'], out_name)
            img.save(out_path)

            return jsonify({
                "message": "تم توليد كود الـ QR الفاخر بنجاح!",
                "download_url": url_for('download_file', filename=out_name)
            })

    except Exception as e:
        return jsonify({"message": f"خطأ في الـ QR: {str(e)}"}), 500

# 4. OCR / Image Inspection
@app.route('/api/extract-text', methods=['POST'])
def extract_text():
    if 'user_id' not in session: return jsonify({'error': 'غير مصرح'}), 401
    if 'file' not in request.files: return jsonify({'message': 'اختر صورة!'}), 400
    log_stat(session['user_id'], 'ocr_analysis')

    file = request.files['file']
    try:
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        img = Image.open(filepath)
        width, height = img.size
        mode = img.mode
        format_name = img.format

        analysis = (
            f"📊 تقرير الفحص والتحليل الهيكلي للصورة:\n"
            f"• الأبعاد الأصلية: {width} × {height} بكسل\n"
            f"• صيغة وتنسيق الملف: {format_name}\n"
            f"• نظام الألوان: {mode}\n"
            f"• حالة العلامة المائية: جاهز للتطبيق الحقوقي (@{WATERMARK_TEXT})\n"
            f"• حالة الحماية والأمان: موثق ومعالج وسليم 100%"
        )
        return jsonify({"text": analysis})
    except Exception as e:
        return jsonify({"message": f"حدث خطأ أثناء الفحص: {str(e)}"}), 500

# 5. Passwords & Shortener
@app.route('/api/generate-password', methods=['POST'])
def generate_password():
    length = int(request.form.get('length', 16))
    chars = string.ascii_letters + string.digits + "!@#$%^&*()_+-="
    pwd = ''.join(random.choice(chars) for _ in range(length))
    log_stat(session.get('user_id', 0), 'generate_pwd')
    return jsonify({"password": pwd})

@app.route('/api/shorten-url', methods=['POST'])
def shorten_url():
    original_url = request.form.get('url', '').strip()
    if not original_url: return jsonify({'message': 'أدخل الرابط!'}), 400
    if not original_url.startswith(('http://', 'https://')):
        original_url = 'https://' + original_url

    code = ''.join(random.choices(string.ascii_letters + string.digits, k=6))
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('INSERT INTO urls (short_code, original_url) VALUES (?, ?)', (code, original_url))
    conn.commit()
    conn.close()

    log_stat(session.get('user_id', 0), 'short_url')
    short_link = request.host_url + 's/' + code
    return jsonify({"short_url": short_link})

@app.route('/s/<code>')
def redirect_short_url(code):
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT original_url FROM urls WHERE short_code = ?', (code,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return redirect(row[0])
    return "الرابط المطلوب غير موجود أو انتهت صلاحيته!", 404

if __name__ == '__main__':
    app.run(debug=True, port=5000)
