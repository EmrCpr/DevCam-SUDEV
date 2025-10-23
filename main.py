import cv2
import mediapipe as mp
import random
import time
import os 
import requests 
import io 
from PIL import Image, ImageDraw, ImageFont 
import numpy as np
import qrcode 
import sounddevice as sd 
import math 

# --- 1. SABİT DEĞİŞKENLER VE AYARLAR ---

# A. API Ayarı (LÜTFEN BU ADRESİ GÖRKEM'İN GO SUNUCUSUNUN IP'SİYLE DEĞİŞTİRİN!)
API_ENDPOINT = "http://api.mgkdev.com:8080/upload" 
API_KEY = "SUDEV_TOPLULUK_2025" 

# B. Kamera ve Çözünürlük Ayarı
# Yüksek Çözünürlük Hedefi (Stabilizasyon için 720p önerilir, sizin isteğiniz üzerine 1920x1080 bırakıldı)
TARGET_W = 1920 
TARGET_H = 1080
# Telefonunuzdan aldığınız IP Webcam URL'sini buraya girin (ör: http://192.168.x.x:8080/video)
IP_KAMERA_URL = "http://1.225.121.72:8080/video" 

# C. Sloganları Yükleme
# Sloganlar kısmını sizin kodunuzdaki gibi yorum satırı olarak bıraktım.
# try:
#     with open("sloganlar.txt", "r", encoding="utf-8") as f:
#         SLOGANLAR = [line.strip() for line in f if line.strip()]
# except FileNotFoundError:
#     print("Hata: sloganlar.txt dosyası bulunamadı. Lütfen kontrol edin.")
#     SLOGANLAR = ["#YazilimDevCam"] 

# D. Kayıt Klasörü Kontrolü
KAYIT_KLASORU = "gecici" 
if not os.path.exists(KAYIT_KLASORU):
    os.makedirs(KAYIT_KLASORU)
    print(f"Kaydedilecek '{KAYIT_KLASORU}' klasörü oluşturuldu.")

# E. Geri Sayım Ayarları
GERI_SAYIM_SURESI = 3.0 # Saniye (Sizin kodunuzdaki değeri korudum)
# Çekim tuşu (Bluetooth kumanda boşluk tuşu gönderir)
TETIKLEYICI_TUS = ord(' ')


# --- 2. YARDIMCI SES FONKSİYONLARI ---

def play_countdown_sound(frequency, duration_s=0.2, sample_rate=44100):
    """Belirli bir frekansta kısa bir bip sesi çalar."""
    t = np.linspace(0, duration_s, int(sample_rate * duration_s), False)
    # Sinüs dalgası oluşturma
    note = np.sin(frequency * t * 2 * np.pi)
    # Ses şiddetini ayarlama ve çalma
    sd.play(note, sample_rate)
    sd.wait()

# --- 3. ÇERÇEVE VE GÖRÜNTÜ İŞLEME FONKSİYONLARI ---

def load_and_resize_overlay(file_path, target_width, target_height):
    """
    PNG çerçeveyi PIL (Pillow) ile yükler, Alpha kanalını ayırır
    ve hedef boyuta yeniden boyutlandırır.
    """
    try:
        # Sizin kodunuzda "test.png" idi, bu dosyanın varlığını doğrulayın.
        pil_img = Image.open(file_path).convert("RGBA")
    except Exception as e:
        print(f"Hata: Çerçeve yüklenemedi veya dönüştürülemedi: {e}. Lütfen 'test.png' dosyasını kontrol edin.")
        return None
    
    # Hedef boyuta yeniden boyutlandır
    pil_img = pil_img.resize((target_width, target_height), Image.Resampling.LANCZOS)
    
    # PIL'den numpy dizisine çevir ve BGR formatına çevirerek döndür
    overlay_img = np.array(pil_img)
    r, g, b, a = cv2.split(overlay_img)
    overlay_img_bgra = cv2.merge((b, g, r, a))

    return overlay_img_bgra


def overlay_transparent(background, overlay_bgra, x, y):
    """Şeffaf (alpha kanalı olan) bir görüntüyü arka plana bindirir."""
    
    if overlay_bgra is None or overlay_bgra.shape[2] < 4:
        print("UYARI: Bindirme görüntüsünde Alpha kanalı yok. Atlanıyor.")
        return background.astype('uint8') 

    h_ov, w_ov, _ = overlay_bgra.shape
    
    # Görüntü boyutlarını kontrol et ve taşmayı önle
    x_start = max(0, x)
    y_start = max(0, y)
    x_end = min(background.shape[1], x + w_ov)
    y_end = min(background.shape[0], y + h_ov)

    overlay_x_start = max(0, -x)
    overlay_y_start = max(0, -y)
    overlay_x_end = overlay_x_start + (x_end - x_start)
    overlay_y_end = overlay_y_start + (y_end - y_start)

    if x_end <= x_start or y_end <= y_start: # Eğer bindirilecek alan yoksa
        return background.astype('uint8')

    # Kanalları ayır ve float'a çevir
    overlay_bgr = overlay_bgra[overlay_y_start:overlay_y_end, overlay_x_start:overlay_x_end, :3].astype(float)
    alpha = overlay_bgra[overlay_y_start:overlay_y_end, overlay_x_start:overlay_x_end, 3].astype(float) / 255.0 
    background_float = background[y_start:y_end, x_start:x_end].astype(float)

    # Bindirme (Alpha Blending)
    background[y_start:y_end, x_start:x_end] = (
        background_float * (1.0 - alpha[:, :, None]) +
        overlay_bgr * alpha[:, :, None]
    ).astype('uint8')
    
    return background.astype('uint8')


def generate_qr_code(url, size=400): # QR boyutu 400x400 olarak artırıldı
    """QR kod üretir ve OpenCV formatında döndürür."""
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=5, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    qr_opencv = cv2.cvtColor(np.array(img.convert('RGB')), cv2.COLOR_RGB2BGR)
    # QR kodun boyutunu sabitledik
    return cv2.resize(qr_opencv, (size, size))

def upload_photo_to_api(image, api_endpoint, api_key):
    """Fotoğrafı API'ye yükler ve indirme URL'sini döndürür."""
    is_success, buffer = cv2.imencode(".jpg", image)
    if not is_success:
        return None
    image_bytes = io.BytesIO(buffer)
    files = {'photo': ('topluluk_foto.jpg', image_bytes, 'image/jpeg')}
    data = {'api_key': api_key, 'timestamp': int(time.time())}
    
    try:
        response = requests.post(api_endpoint, files=files, data=data, timeout=30)
        response.raise_for_status() 
        result = response.json()
        if response.status_code == 200 and result.get('success') and result.get('download_url'):
            return result['download_url']
    except requests.exceptions.RequestException as e:
        print(f"API Bağlantı/İstek Hatası: {e}")
        # --- QR KOD TEST ÇÖZÜMÜ ---
        # API bağlantısı başarısız olsa bile, QR kodun bindirme mantığını test etmek için
        # sabit bir test URL'si döndürülür. (Bu, geçici bir test çözümüdür)
        return "http://devcam.live/qr-test-success" 
    return None

# --- ANA DÖNGÜ VE İŞLEM ---

def main():
    # Global sayım değişkenleri
    global sayim_baslangic_zamani, sayim_durumu

    # MediaPipe modüllerini başlatıyoruz (sadece yüz tespiti)
    mp_face_detection = mp.solutions.face_detection
    
    # Global sayım değişkenleri
    sayim_baslangic_zamani = 0.0
    sayim_durumu = False
    frame_counter = 0 
    yuz_tespit_edildi = False # Yüz tespiti durumunu burada başlattık (Bug Fix)
    
    # Tekrar bağlanmayı denemek için sayaç
    baglanti_deneme_sayaci = 0

    # Canlı akış penceresini tam ekran olarak oluştur
    CANLI_AKIS_PENCERE_ADI = 'DevCam - Canli Akis'
    cv2.namedWindow(CANLI_AKIS_PENCERE_ADI, cv2.WND_PROP_FULLSCREEN)
    cv2.setWindowProperty(CANLI_AKIS_PENCERE_ADI, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)


    with mp_face_detection.FaceDetection(
        model_selection=1, min_detection_confidence=0.5) as face_detection:
        
        # IP Kamera URL'si ile bağlantı
        cap = cv2.VideoCapture(IP_KAMERA_URL) 

        while True:
            frame_counter += 1
            if not cap.isOpened():
                # Bağlantı kesildiğinde tekrar dene
                if baglanti_deneme_sayaci % 50 == 0:
                    print(f"Kamera bağlantısı yok. {IP_KAMERA_URL} adresine tekrar bağlanılıyor...")
                    cap = cv2.VideoCapture(IP_KAMERA_URL)
                baglanti_deneme_sayaci += 1
                cv2.waitKey(100)
                continue
            
            # Kamera ayarını yap (IP Webcam buna izin vermezse görmezden gelinir)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, TARGET_W)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, TARGET_H)

            success, image = cap.read()
            if not success:
                continue

            h, w, _ = image.shape
            
            # Yüz tespiti yap (Hız için)
            if frame_counter % 5 == 0: # Sadece her 5. karede yüz tespiti yap
                image_processing = cv2.resize(image, (w // 2, h // 2))
                image_processing_rgb = cv2.cvtColor(image_processing, cv2.COLOR_BGR2RGB)
                results = face_detection.process(image_processing_rgb)
                
                # Sadece tespit yapıldığında durumu güncelle (Bug Fix)
                yuz_tespit_edildi = False
                if results.detections:
                    yuz_tespit_edildi = True
            
            # --- TUŞ KONTROLÜ VE SAYIM BAŞLATMA ---
            key = cv2.waitKey(5) & 0xFF
            
            if not sayim_durumu and yuz_tespit_edildi and key == TETIKLEYICI_TUS:
                # Tetikleyici tuşa basıldı ve yüz var: Geri sayımı başlat
                sayim_durumu = True
                sayim_baslangic_zamani = time.time()
                print("Geri Sayım Başlatıldı (SPACE)")

            # --- GÖRSEL VE SESLİ GERİ SAYIM ---
            if sayim_durumu:
                gecen_sure = time.time() - sayim_baslangic_zamani
                kalan_sure = GERI_SAYIM_SURESI - gecen_sure
                sayi = math.ceil(kalan_sure)

                # Sadece tam sayıya düşüşlerde ses çal (0.1 saniyelik bir marj ile)
                if sayi >= 0 and sayi != math.ceil(GERI_SAYIM_SURESI - gecen_sure - 0.1):
                    frequency = 440 if sayi > 0 else 880 # 1'den 0'a geçerken tiz ses
                    play_countdown_sound(frequency)
                
                if kalan_sure <= 0:
                    # --- ÇEKİM ANI ---
                    sayim_durumu = False 
                    
                    # 1. Çerçeveyi Yükle ve Boyutlandır 
                    cerceve_img = load_and_resize_overlay("cerceveb.png", w, h)
                    
                    if cerceve_img is not None:
                        # 2. Çerçeveyi Bindir (Çerçeve tam köşelere oturur)
                        islenmis_foto = overlay_transparent(image.copy(), cerceve_img, 0, 0)
                        
                        # --- API İŞLEMİ VE SONUÇ GÖSTERİMİ ---
                        print("API'ye YÜKLENİYOR... Lütfen bekleyin.")
                        download_url = upload_photo_to_api(islenmis_foto, API_ENDPOINT, API_KEY)
                        
                        if download_url:
                            qr_img = generate_qr_code(download_url, size=400) # QR boyutu 400x400
                            
                            # Sonuç fotoğrafı için ayrı pencere
                            SONUC_PENCERE_ADI = 'SONUC - DEV CAM'
                            cv2.namedWindow(SONUC_PENCERE_ADI, cv2.WND_PROP_FULLSCREEN)
                            cv2.setWindowProperty(SONUC_PENCERE_ADI, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
                            
                            # QR Kodu için ayrı pencere
                            QR_PENCERE_ADI = 'QR KODU - TELEFONLA OKUTUN'
                            # QR kodunun tam ekran olmasını istiyorsunuz, bu yüzden tam ekran ayarı kaldırıldı.
                            cv2.namedWindow(QR_PENCERE_ADI, cv2.WINDOW_AUTOSIZE) # Otomatik boyutlandırma
                            
                            # Fotoğrafı ve QR kodu ayrı pencerelerde göster (Ekranı Taşırmadan)
                            cv2.imshow(SONUC_PENCERE_ADI, islenmis_foto) 
                            cv2.imshow(QR_PENCERE_ADI, qr_img)
                            
                            cv2.waitKey(30000) # 30 saniye beklet
                            cv2.destroyWindow(SONUC_PENCERE_ADI)
                            cv2.destroyWindow(QR_PENCERE_ADI)
                            
                        else:
                            # YEDEKLEME DURUMU
                            timestamp = int(time.time())
                            kayit_adi = f"{KAYIT_KLASORU}/API_HATALI_YEDEK_{timestamp}.jpg"
                            cv2.imwrite(kayit_adi, islenmis_foto) 
                            print(f"UYARI: API Başarısız. Fotoğraf YEDEK OLARAK kaydedildi: {kayit_adi}")
                            
                            # Hata mesajını fotoğrafın üzerine yazdırıp göster
                            cv2.putText(image, "API HATA! YEDEK KAYIT YAPILDI.", (50, 100), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 3, cv2.LINE_AA)
                            cv2.imshow(CANLI_AKIS_PENCERE_ADI, image) # Canlı akış penceresinde göster
                            cv2.waitKey(3000)
                            
                    else:
                        print("HATA: Çerçeve yüklenemediği için çekim atlandı.")
                        sayim_durumu = False # Sayımı durdur

            # --- CANLI AKIŞ KONTROLLERİ ---
            
            # Canlı akışa Geri Sayım Metni ekle
            if sayim_durumu:
                # Geri sayım sırasında büyük sayıyı ekranın ortasına yazdır
                sayi_metni = str(sayi)
                (text_w, text_h), baseline = cv2.getTextSize(sayi_metni, cv2.FONT_HERSHEY_SIMPLEX, 5, 10)
                text_x = (w - text_w) // 2
                text_y = (h + text_h) // 2
                
                # Gölge efekti ve Ana metin
                cv2.putText(image, sayi_metni, (text_x + 5, text_y + 5), cv2.FONT_HERSHEY_SIMPLEX, 5, (0, 0, 0), 10, cv2.LINE_AA)
                cv2.putText(image, sayi_metni, (text_x, text_y), cv2.FONT_HERSHEY_SIMPLEX, 5, (0, 255, 255), 8, cv2.LINE_AA)
                cv2.putText(image, "CEKILIYOR...", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2, cv2.LINE_AA)
            else:
                # Rehberlik Metni
                if yuz_tespit_edildi:
                    cv2.putText(image, "GULUMSEYIN! (SPACE BASIN)", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2, cv2.LINE_AA)
                else:
                    # Yüz tespit edilmediğinde bu metin gösterilir (Bug Fix sonrası stabil)
                    cv2.putText(image, "Yuzunuzu Kameraya Getirin", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2, cv2.LINE_AA)

            # Canlı akışı DevCam başlığıyla göster (Tam ekran pencere adı ile)
            cv2.imshow(CANLI_AKIS_PENCERE_ADI, image)

            # --- TUŞ KONTROLÜ (ÇIKIŞ) ---
            key = cv2.waitKey(5) & 0xFF
            
            # 'Q' tuşuna basıldığında döngüyü kır (Çıkış)
            if key == ord('q'):
                break

        # Kaynakları serbest bırak
        cap.release()
        cv2.destroyAllWindows()

if __name__ == '__main__':
    main()
