import cv2
import mediapipe as mp
import random
import time
import os 
import requests 
import io 
from PIL import Image # Pil kütüphanesini kullanacağız
import numpy as np
import qrcode 

# --- 1. SABİT DEĞİŞKENLER VE AYARLAR ---

# A. API Ayarı (Lütfen bu adresi kendi sunucunuzla değiştirin!)
API_ENDPOINT = "http://seninwebsiten.com/api/fotograf_yukle" 
API_KEY = "SUDEV_TOPLULUK_2025" 

# B. Sloganları Yükleme (Kaldırıldı, ancak kodu koruyoruz)
try:
    with open("sloganlar.txt", "r", encoding="utf-8") as f:
        # Sloganlar kaldırıldı, sadece tek bir mesaj gösterilecek
        SLOGANLAR = [""] 
except FileNotFoundError:
    SLOGANLAR = [""] 

# C. MediaPipe Modülü (El Tespiti Kaldırıldı, sadece Yüz Tespiti kaldı)
mp_face_detection = mp.solutions.face_detection

# D. Kayıt Klasörü Kontrolü (Yedekleme için)
KAYIT_KLASORU = "gecici" 
if not os.path.exists(KAYIT_KLASORU):
    os.makedirs(KAYIT_KLASORU)

# E. IP Kamera Ayarı ve Çözünürlük (Yüksek Kalite İçin)
# IP Webcam URL'sini buraya yapıştırın. (Örn: "http://192.168.1.10:8080/video")
IP_KAMERA_URL = "http://192.168.0.2:8080/video" 

# Yüksek Çözünürlük Hedefi (5 kişi sığması için 1080p önerilir)
TARGET_W = 1920
TARGET_H = 1080
GERI_SAYIM_SURESI = 3 # Saniye


# --- 2. YARDIMCI FONKSİYONLAR ---

def load_and_resize_overlay(file_path, target_width, target_height):
    """
    PNG çerçeveyi PIL (Pillow) ile yükler, Alpha kanalını ayırır
    ve hedef boyuta yeniden boyutlandırır.
    """
    try:
        # PIL ile aç ve RGBA formatına çevir
        pil_img = Image.open(file_path).convert("RGBA")
    except Exception as e:
        print(f"Hata: Çerçeve yüklenemedi veya dönüştürülemedi: {e}")
        return None
    
    # Hedef boyuta yeniden boyutlandır
    pil_img = pil_img.resize((target_width, target_height), Image.Resampling.LANCZOS)
    
    # PIL'den numpy dizisine çevir ve BGRA olarak yeniden birleştir
    overlay_img = np.array(pil_img)
    r, g, b, a = cv2.split(overlay_img)
    overlay_img_bgra = cv2.merge((b, g, r, a))
    
    return overlay_img_bgra


def overlay_transparent(background, overlay_bgra, x, y):
    """Şeffaf (alpha kanalı olan) bir görüntüyü arka plana bindirir."""
    
    h, w, _ = background.shape
    
    if overlay_bgra is None or overlay_bgra.shape[2] < 4:
        # Eğer çerçeve yoksa, arka planı döndür
        return background.astype('uint8') 

    # Çerçeve ve arka planı float'a çevir
    background_float = background.astype(float)
    overlay_float = overlay_bgra.astype(float) 

    overlay_bgr = overlay_float[:, :, :3]
    alpha = overlay_float[:, :, 3] / 255.0

    bg_roi = background_float[y:y + h, x:x + w]
    bg_part = bg_roi * (1.0 - alpha[:, :, None])
    overlay_part = overlay_bgr * alpha[:, :, None]
    
    background_float[y:y + h, x:x + w] = bg_part + overlay_part
    
    return background_float.astype('uint8')


# --- YENİ FONKSİYONLAR (API VE QR) ---
def generate_qr_code(url, size=300):
    """Verilen URL için QR kodu oluşturur."""
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=5, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    qr_opencv = cv2.cvtColor(np.array(img.convert('RGB')), cv2.COLOR_RGB2BGR)
    return cv2.resize(qr_opencv, (size, size))

def upload_photo_to_api(image, api_endpoint, api_key):
    """İşlenmiş fotoğrafı API'ye yükler."""
    is_success, buffer = cv2.imencode(".jpg", image)
    if not is_success:
        return None
    image_bytes = io.BytesIO(buffer)
    files = {'photo': ('topluluk_foto.jpg', image_bytes, 'image/jpeg')}
    data = {'api_key': api_key, 'timestamp': int(time.time())}
    try:
        response = requests.post(api_endpoint, files=files, data=data, timeout=15)
        response.raise_for_status() 
        result = response.json()
        if response.status_code == 200 and result.get('status') == 'success' and result.get('download_url'):
            return result['download_url']
    except requests.exceptions.RequestException as e:
        print(f"API Bağlantı/İstek Hatası: {e}")
        return None
    return None

# --- 3. ANA DÖNGÜ VE İŞLEM ---

# Geri sayım durumu
sayim_aktif = False
sayim_baslangic_zamani = 0

with mp_face_detection.FaceDetection(
    model_selection=1, min_detection_confidence=0.5) as face_detection:
    
    # IP Kamera URL'si ile bağlantı kurmayı dene (0 yerine URL)
    cap = cv2.VideoCapture(IP_KAMERA_URL)
    
    # Çözünürlüğü ayarla
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, TARGET_W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, TARGET_H)

    if not cap.isOpened():
        # IP kamera başarısız olursa 0'ı dene
        cap = cv2.VideoCapture(0)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, TARGET_W)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, TARGET_H)
        if not cap.isOpened():
             print("Hata: Kamera açılamadı. IP Kamera ve Yerel Kamera (0) kullanılamıyor.")
             exit()

    while cap.isOpened():
        success, image = cap.read()
        if not success:
            continue
        
        # Görüntü işlemeden önce BGR'dan RGB'ye dönüştür
        image.flags.writeable = False
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        results = face_detection.process(image)
        
        # Tekrar BGR'ye çevir
        image.flags.writeable = True
        image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        
        h, w, _ = image.shape
        
        # --- Dinamik Ekran Boyutu İçin Görüntüyü Ölçekle (YENİ) ---
        # Görüntüyü ekrana sığdırmak için yarı boyuta düşür
        display_w = w // 2 
        display_h = h // 2
        display_image = cv2.resize(image, (display_w, display_h))
        
        
        # Yüz Tespiti Kontrolü
        yuz_tespit_edildi = bool(results.detections)
        
        # --- EKRAN GÖSTERGELERİ ---
        
        if sayim_aktif:
            kalan_sure = GERI_SAYIM_SURESI - int(time.time() - sayim_baslangic_zamani)
            
            # Geri Sayım Metni
            if kalan_sure > 0:
                mesaj = f"GULUMSEYIN! {kalan_sure}"
                
                # Mesajı ölçeklenmiş görüntü üzerine yaz
                cv2.putText(display_image, mesaj, (display_w // 2 - 150, display_h // 2), 
                            cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 255), 4, cv2.LINE_AA) # Font boyutları ölçeklendi
            else:
                # Geri Sayım Bitti - Çekim Anı (Kod çekimi burada yapar)
                
                # 1. Çerçeveyi Yükle ve Boyutlandır (ORİJİNAL, YÜKSEK ÇÖZÜNÜRLÜKLÜ GÖRÜNTÜ KULLANILIR)
                cerceve_img = load_and_resize_overlay("cerceve.png", w, h)
                
                if cerceve_img is not None:
                    # 2. Çerçeveyi Bindir 
                    islenmis_foto = overlay_transparent(image.copy(), cerceve_img, 0, 0)
                    
                    # 3. Slogan Metni (Kaldırıldı, ama boş string yollanıyor)
                    rastgele_slogan = random.choice(SLOGANLAR)
                    
                    if rastgele_slogan:
                         slogan_gosterimi = rastgele_slogan.replace('ğ', 'g').replace('ı', 'i').replace('ş', 's').replace('ü', 'u').replace('ö', 'o').replace('ç', 'c')
                         text_size = cv2.getTextSize(slogan_gosterimi, cv2.FONT_HERSHEY_SIMPLEX, 1, 2)[0]
                         text_x = (w - text_size[0]) // 2 
                         text_y = h - 30 
                         cv2.putText(islenmis_foto, slogan_gosterimi, (text_x, text_y), 
                                    cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2, cv2.LINE_AA)
                    
                    # 4. API İşlemi (Bu aşamadan sonra API başlar)
                    print("API'ye YÜKLENİYOR... Lütfen bekleyin.")
                    download_url = upload_photo_to_api(islenmis_foto, API_ENDPOINT, API_KEY)
                    
                    if download_url:
                        # Başarılı QR Kod Gösterimi
                        print(f"BAŞARILI: İndirme Linki Alındı: {download_url}")
                        qr_img = generate_qr_code(download_url)
                        
                        cv2.imshow('SONUC', islenmis_foto) 
                        cv2.imshow('QR KODU - TELEFONLA OKUTUN', qr_img)
                        
                        cv2.waitKey(15000) # 15 saniye bekle
                        cv2.destroyWindow('SONUC')
                        cv2.destroyWindow('QR KODU - TELEFONLA OKUTUN')
                    
                    else:
                        # YEDEKLEME
                        timestamp = int(time.time())
                        kayit_adi = f"{KAYIT_KLASORU}/API_HATALI_YEDEK_{timestamp}.jpg"
                        cv2.imwrite(kayit_adi, islenmis_foto) 
                        print(f"UYARI: API Başarısız. Fotoğraf YEDEK OLARAK kaydedildi: {kayit_adi}")
                        
                        # Hata mesajını ölçeklenmiş görüntü üzerine yaz
                        cv2.putText(display_image, "API HATA! YEDEK KAYIT YAPILDI.", (50, 100), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 3, cv2.LINE_AA)
                        cv2.imshow('DevCam - Canli Akis', display_image)
                        cv2.waitKey(3000)

                # Sayımı sıfırla
                sayim_aktif = False
                sayim_baslangic_zamani = 0


        else: # Sayım aktif değilse
            if yuz_tespit_edildi:
                cv2.putText(display_image, "Hazir (S) Tusu", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2, cv2.LINE_AA)
            else:
                 cv2.putText(display_image, "Kameraya Bakin...", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2, cv2.LINE_AA)
            
            # Tuş Kontrolü
            key = cv2.waitKey(5) & 0xFF
            if key == ord('s') and yuz_tespit_edildi:
                sayim_aktif = True
                sayim_baslangic_zamani = time.time()
                print("Geri sayım S tuşu ile başlatıldı.")
            
            elif key == ord('q'):
                break

        # Canlı akışı DevCam başlığıyla göster
        # Ölçeklenmiş görüntüyü göster
        cv2.imshow('DevCam - Canli Akis', display_image)

    # Kaynakları serbest bırak
    cap.release()
    cv2.destroyAllWindows()
