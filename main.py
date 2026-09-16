from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import sqlite3
import os
import shutil
import math
from datetime import datetime
from deepface import DeepFace

app = FastAPI()

templates = Jinja2Templates(directory="templates")

os.makedirs("dataset", exist_ok=True)
os.makedirs("static/uploads", exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")

KANTOR_LAT = -7.4443  
KANTOR_LON = 112.7114 
RADIUS_MAKSIMAL_METER = 1500000

def hitung_jarak(lat1, lon1, lat2, lon2):
    R = 6371000  
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi/2.0)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda/2.0)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def tentukan_status_kehadiran(waktu_str, jenis_absen="Masuk"):
    try:
        if "Lembur" in jenis_absen:
            return "Shift Lembur (10.00 - 22.00)"

        waktu_absen = datetime.strptime(waktu_str, "%Y-%m-%d %H:%M:%S")
        menit_absen = waktu_absen.hour * 60 + waktu_absen.minute
        
        # Shift 1: Masuk pukul 10.00
        if 300 <= menit_absen <= 720:
            batas_tepat = 10 * 60          
            if menit_absen < batas_tepat:
                return "Shift 1: Hadir Lebih Awal"
            elif menit_absen == batas_tepat:
                return "Shift 1: Tepat Waktu"
            else:
                return "Shift 1: Terlambat"
                
        # Shift 2: Masuk pukul 14.00 
        elif 721 <= menit_absen <= 1020:
            batas_tepat = 14 * 60          
            batas_toleransi = 14 * 60 + 15 
            if menit_absen < batas_tepat:
                return "Shift 2: Hadir Lebih Awal"
            elif menit_absen <= batas_tepat:
                return "Shift 2: Tepat Waktu"
            elif menit_absen <= batas_toleransi:
                return "Shift 2: Tepat Waktu (Toleransi)"
            else:
                return "Shift 2: Terlambat"
        else:
            return "Diluar Jam Shift Utama"
    except Exception as e:
        return "Tepat Waktu"

def init_db():
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS karyawan (
            kode TEXT PRIMARY KEY,
            nama TEXT,
            status TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS log_absensi (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kode_karyawan TEXT,
            latitude REAL,
            longitude REAL,
            foto_absen TEXT,
            status_kehadiran TEXT,
            jenis_absen TEXT,
            waktu TEXT
        )
    ''')
    
    try:
        cursor.execute("ALTER TABLE log_absensi ADD COLUMN jenis_absen TEXT")
    except:
        pass

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS laporan_error (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kode_karyawan TEXT,
            keterangan TEXT,
            waktu DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

init_db()

@app.get("/")
async def halaman_utama(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

@app.post("/api/absen")
async def proses_absen(
    file: UploadFile = File(...),
    latitude: float = Form(...),
    longitude: float = Form(...),
    waktu_lokal: str = Form(...),
    jenis_absen: str = Form(...)
):
    jarak = hitung_jarak(latitude, longitude, KANTOR_LAT, KANTOR_LON)
    if jarak > RADIUS_MAKSIMAL_METER:
        return JSONResponse(content={"status": "ditolak", "pesan": f"Absen ditolak! Anda berada di luar radius kantor ({int(jarak)} meter)."})

    temp_image = "temp_capture.jpg"
    with open(temp_image, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        hasil = DeepFace.find(
            img_path=temp_image, 
            db_path="dataset", 
            model_name="Facenet",         
            detector_backend="mtcnn",
            enforce_detection=False
        )

        if len(hasil) > 0 and not hasil[0].empty:
            file_wajah = hasil[0]['identity'][0]
            kode_karyawan = os.path.basename(file_wajah).split('_')[0]

            conn = sqlite3.connect("database.db")
            cursor = conn.cursor()
            cursor.execute("SELECT nama, status FROM karyawan WHERE kode = ?", (kode_karyawan,))
            data_karyawan = cursor.fetchone()

            if not data_karyawan:
                if os.path.exists(temp_image): os.remove(temp_image)
                return JSONResponse(content={"status": "error", "pesan": "Wajah dikenali tapi data tidak ada di DB."})

            nama, status = data_karyawan

            if status != "aktif":
                if os.path.exists(temp_image): os.remove(temp_image)
                return JSONResponse(content={"status": "ditolak", "pesan": f"Akses ditolak. {nama} sudah bukan karyawan aktif."})

            if "Masuk" in jenis_absen:
                status_hadir = tentukan_status_kehadiran(waktu_lokal, jenis_absen)
            else:
                status_hadir = jenis_absen

            nama_file_absen = f"{kode_karyawan}_{waktu_lokal.replace(':', '-').replace(' ', '_')}.jpg"
            path_simpan = os.path.join("static/uploads", nama_file_absen)
            shutil.copy(temp_image, path_simpan)
            
            if os.path.exists(temp_image): os.remove(temp_image)

            cursor.execute(
                "INSERT INTO log_absensi (kode_karyawan, latitude, longitude, foto_absen, status_kehadiran, jenis_absen, waktu) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (kode_karyawan, latitude, longitude, nama_file_absen, status_hadir, jenis_absen, waktu_lokal)
            )
            conn.commit()
            conn.close()

            return JSONResponse(content={"status": "sukses", "pesan": f"Berhasil absen {jenis_absen}! Status: {status_hadir}."})
        
        else:
            if os.path.exists(temp_image): os.remove(temp_image)
            return JSONResponse(content={"status": "error", "pesan": "Wajah tidak terdaftar di sistem."})

    except Exception as e:
        if os.path.exists(temp_image): os.remove(temp_image)
        return JSONResponse(content={"status": "error", "pesan": "Gagal mendeteksi wajah. Pastikan cahaya terang!"})

@app.get("/api/rekap/{kode}")
async def get_rekap(kode: str):
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT nama FROM karyawan WHERE kode = ?", (kode,))
    user = cursor.fetchone()
    
    if not user:
        conn.close()
        return JSONResponse(content={"status": "error", "pesan": "Kode karyawan tidak ditemukan."})
    
    nama = user[0]
    cursor.execute("SELECT waktu, latitude, longitude, status_kehadiran, jenis_absen FROM log_absensi WHERE kode_karyawan = ? ORDER BY id DESC", (kode,))
    
    riwayat = []
    for row in cursor.fetchall():
        riwayat.append({
            "waktu": row[0], 
            "lat": row[1], 
            "lon": row[2],
            "status_hadir": row[3],
            "jenis_absen": row[4] if row[4] else "Masuk"
        })
        
    conn.close()
    
    return JSONResponse(content={"status": "sukses", "nama": nama, "riwayat": riwayat})

@app.post("/api/lapor-error")
async def lapor_error(kode: str = Form(...), keterangan: str = Form(...)):
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT nama FROM karyawan WHERE kode = ?", (kode,))
    user = cursor.fetchone()
    
    if not user:
        conn.close()
        return JSONResponse(content={"status": "error", "pesan": "Kode karyawan tidak valid."})
        
    cursor.execute("INSERT INTO laporan_error (kode_karyawan, keterangan) VALUES (?, ?)", (kode, keterangan))
    conn.commit()
    conn.close()
    
    return JSONResponse(content={"status": "sukses", "pesan": "Laporan error berhasil dikirim ke Owner."})

@app.get("/admin")
async def halaman_admin(request: Request):
    return templates.TemplateResponse(request=request, name="admin.html")

@app.post("/api/admin/login")
async def admin_login(password: str = Form(...)):
    if password == "admin123":
        return JSONResponse(content={"status": "sukses"})
    return JSONResponse(content={"status": "error", "pesan": "Password salah!"})

@app.get("/api/admin/karyawan")
async def get_all_karyawan():
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT kode, nama, status FROM karyawan")
    data = [{"kode": row[0], "nama": row[1], "status": row[2]} for row in cursor.fetchall()]
    conn.close()
    return data

@app.post("/api/admin/tambah-karyawan")
async def tambah_karyawan(
    kode: str = Form(...),
    nama: str = Form(...),
    file: UploadFile = File(...)
):
    nama_file_foto = f"{kode}_{nama.replace(' ', '')}.jpg"
    path_foto = os.path.join("dataset", nama_file_foto)
    
    with open(path_foto, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO karyawan (kode, nama, status) VALUES (?, ?, ?)",
            (kode, nama, 'aktif')
        )
        conn.commit()
        conn.close()
        return JSONResponse(content={"status": "sukses", "pesan": "Karyawan berhasil ditambah & wajah terekam!"})
    except sqlite3.IntegrityError:
        conn.close()
        return JSONResponse(content={"status": "error", "pesan": "Kode karyawan sudah terdaftar di sistem!"})

@app.post("/api/admin/ubah-status")
async def ubah_status(kode: str = Form(...), status: str = Form(...)):
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE karyawan SET status = ? WHERE kode = ?", (status, kode))
    conn.commit()
    conn.close()
    return JSONResponse(content={"status": "sukses"})

@app.get("/api/admin/log-absensi")
async def get_log_absensi():
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute('''
        SELECT l.waktu, k.kode, k.nama, l.latitude, l.longitude, l.foto_absen, l.status_kehadiran, l.jenis_absen 
        FROM log_absensi l 
        JOIN karyawan k ON l.kode_karyawan = k.kode 
        ORDER BY l.id DESC LIMIT 100
    ''')
    data = []
    for row in cursor.fetchall():
        jenis = row[7] if row[7] else "Masuk"
        data.append({
            "waktu": row[0], 
            "kode": row[1], 
            "nama": row[2], 
            "lat": row[3], 
            "lon": row[4], 
            "foto": row[5], 
            "status_hadir": row[6], 
            "jenis_absen": jenis
        })
    conn.close()
    return data

@app.get("/api/admin/laporan-error")
async def get_laporan_error():
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute('''
        SELECT l.waktu, k.kode, k.nama, l.keterangan 
        FROM laporan_error l 
        JOIN karyawan k ON l.kode_karyawan = k.kode 
        ORDER BY l.id DESC LIMIT 50
    ''')
    data = [{
        "waktu": row[0], 
        "kode": row[1], 
        "nama": row[2], 
        "keterangan": row[3]
    } for row in cursor.fetchall()]
    conn.close()
    return data

@app.delete("/api/admin/hapus-karyawan/{kode}")
async def hapus_karyawan(kode: str):
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    
    cursor.execute("SELECT nama FROM karyawan WHERE kode = ?", (kode,))
    user = cursor.fetchone()
    
    if not user:
        conn.close()
        return JSONResponse(content={"status": "error", "pesan": "Karyawan tidak ditemukan."})
    
    for filename in os.listdir("dataset"):
        if filename.startswith(kode):
            file_path = os.path.join("dataset", filename)
            if os.path.exists(file_path):
                os.remove(file_path)

    cursor.execute("DELETE FROM karyawan WHERE kode = ?", (kode,))
    cursor.execute("DELETE FROM log_absensi WHERE kode_karyawan = ?", (kode,))
    cursor.execute("DELETE FROM laporan_error WHERE kode_karyawan = ?", (kode,))
    
    conn.commit()
    conn.close()
    
    return JSONResponse(content={"status": "sukses", "pesan": "Karyawan dan data terkait berhasil dihapus permanen."})