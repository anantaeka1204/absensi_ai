import sqlite3

# Membuka koneksi ke database
conn = sqlite3.connect("database.db")
cursor = conn.cursor()

# Menambahkan data Anda (Pastikan kodenya sama dengan nama file foto)
kode_karyawan = 'KRY001'
nama_karyawan = 'Ananta' # Silakan ubah sesuai nama Anda

try:
    cursor.execute(
        "INSERT INTO karyawan (kode, nama, status) VALUES (?, ?, ?)",
        (kode_karyawan, nama_karyawan, 'aktif')
    )
    conn.commit()
    print(f"Sukses! {nama_karyawan} berhasil didaftarkan sebagai karyawan aktif.")
except sqlite3.IntegrityError:
    print("Error: Kode karyawan tersebut sudah terdaftar!")

conn.close()