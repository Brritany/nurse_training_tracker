import os
import uuid
import pandas as pd
from flask import Flask, request, send_file, render_template, after_this_request, abort
from datetime import datetime
from werkzeug.utils import secure_filename

app = Flask(__name__)

UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

ALLOWED_EXTENSIONS = {'xlsx'}
MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5MB 限制
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH

# 使用者檔案暫存，用 uid 映射
session_files = {}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    return render_template('upload.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'major_file' not in request.files or 'basic_file' not in request.files:
        return "請上傳兩個檔案", 400

    major_file = request.files['major_file']
    basic_file = request.files['basic_file']

    if not allowed_file(major_file.filename) or not allowed_file(basic_file.filename):
        return "請上傳 xlsx 格式檔案", 400

    uid = uuid.uuid4().hex
    major_filename = f"{uid}_major.xlsx"
    basic_filename = f"{uid}_basic.xlsx"
    summary_filename = f"{uid}_summary.xlsx"

    major_path = os.path.join(app.config['UPLOAD_FOLDER'], major_filename)
    basic_path = os.path.join(app.config['UPLOAD_FOLDER'], basic_filename)
    summary_path = os.path.join(app.config['UPLOAD_FOLDER'], summary_filename)

    try:
        major_file.save(major_path)
        basic_file.save(basic_path)
    except Exception:
        abort(413, description="檔案儲存失敗，可能超過 5MB")

    stat = run_analysis(major_path, basic_path, summary_path)
    session_files[uid] = [major_path, basic_path, summary_path]
    return render_template('success.html', uid=uid, stat=stat)

@app.route('/download/<uid>')
def download_summary(uid):
    if uid not in session_files:
        return "找不到此檔案", 404

    paths = session_files.pop(uid)
    summary_path = paths[2]

    @after_this_request
    def cleanup(response):
        for f in paths:
            try:
                os.remove(f)
            except Exception as e:
                print("❌ 清除失敗：", e)
        return response

    return send_file(summary_path, as_attachment=True, download_name="summary.xlsx")

def run_analysis(file_major, file_basic, output_path):
    df_major = pd.read_excel(file_major, skiprows=7)
    df_basic = pd.read_excel(file_basic, skiprows=7)

    this_year = pd.Timestamp.now().year
    df_major["完成日期"] = pd.to_datetime(df_major["完成日期"], errors="coerce")
    df_major["時數"] = pd.to_numeric(df_major["時數"], errors="coerce")
    df_basic["完成日期"] = pd.to_datetime(df_basic["完成日期"], errors="coerce")
    df_basic["時數"] = pd.to_numeric(df_basic["時數"], errors="coerce")

    df_major_y = df_major[df_major["完成日期"].dt.year >= this_year]
    df_basic_y = df_basic[df_basic["完成日期"].dt.year >= this_year]

    total_major = df_major_y["時數"].sum()
    total_basic = df_basic_y["時數"].sum()

    stat = {
        "一般": total_basic,
        "專業": total_major,
        "急重症": df_major_y[df_major_y["類別"] == "急重症護理"]["時數"].sum(),
        "跨領域": df_major_y[df_major_y["類別"].str.contains("跨領域", na=False)]["時數"].sum(),
        "消防安全": df_basic_y[df_basic_y["類別"] == "1.4(FMS)消防安全"]["時數"].sum(),
        "師培": df_major_y[df_major_y["類別"].str.contains("師資培育|師培課程", na=False)]["時數"].sum(),
        "感控": df_basic_y[df_basic_y["類別"].str.contains("結核病防治|抗生素使用|手部衛生|傳染病教育|新興與再浮現傳染病防治", na=False)]["時數"].sum(),
        "病人權利": df_basic_y[df_basic_y["課程名稱"].str.contains("權利", na=False)]["時數"].sum(),
        "病人安全": df_basic_y[df_basic_y["類別"].str.contains("病人安全", na=False)]["時數"].sum(),
    }

    three_years_ago = pd.Timestamp.now() - pd.DateOffset(years=3)
    df_major_3y = df_major[df_major["完成日期"] >= three_years_ago]
    df_basic_3y = df_basic[df_basic["完成日期"] >= three_years_ago]

    def match_sum(df, keywords):
        return df[df["類別"].str.contains(keywords, na=False)]["時數"].sum()

    stat.update({
        "醫護倫理": match_sum(df_major_3y, "醫護倫理"),
        "全人醫療": match_sum(df_major_3y, "全人醫療"),
        "哀傷輔導": match_sum(df_major_3y, "哀傷輔導"),
        "危機處理": match_sum(df_major_3y, "危機處理"),
        "醫療品質": match_sum(df_basic_3y, "服務品質類|品管基礎|品管工具|服務禮儀|品管進階"),
        "醫病溝通": match_sum(df_major_3y, "醫病溝通"),
        "護理紀錄": match_sum(df_major_3y, "護理紀錄"),
        "醫事法規": match_sum(df_basic_3y, "政策法規|環境教育|當前政府重大政策|性別教育|衛生醫療法令|行政中立"),
        "實證醫學": match_sum(df_major_3y, "實證醫學")
    })

    pd.DataFrame([stat]).to_excel(output_path, index=False)

@app.errorhandler(413)
def file_too_large(e):
    return render_template("error.html", message="上傳檔案超過 5MB 限制，請重新選擇較小的檔案。"), 413

@app.errorhandler(400)
@app.errorhandler(404)
@app.errorhandler(500)
def general_error(e):
    return render_template("error.html", message=str(e)), e.code if hasattr(e, 'code') else 500

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000)
