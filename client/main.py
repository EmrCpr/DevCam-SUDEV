import cv2
import mediapipe as mp
import random
import time
import os 
import requests 
import io 
from PIL import Image
import numpy as np
import qrcode 

# --- 1. SABİT DEĞİŞKENLER VE AYARLAR ---

# A. API Ayarı (Lütfen bu adresi kendi sunucunuzla değiştirin!)
API_ENDPOINT = "http://localhost:8080/upload" 
API_KEY = "SUDEV_TOPLULUK_2025" 

# B. Sloganları Yükleme
try:
    with open("sloganlar.txt", "r", encoding="utf-8") as f:
        SLOGANLAR = [line.strip() for line in f if line.strip()]
except FileNotFoundError:
    print("Hata: sloganlar.txt dosyası bulunamadı. Lütfen kontrol edin.")
    SLOGANLAR = ["#VarsayilanSlogan"] 

# C. MediaPipe Modülleri
mp_face_detection = mp.solutions.face_detection
mp_hands = mp.solutions.hands 
mp_drawing = mp.solutions.drawing_utils 

# D. Kayıt Klasörü Kontrolü
KAYIT_KLASORU = "gecici" 
if not os.path.exists(KAYIT_KLASORU):
    os.makedirs(KAYIT_KLASORU)
    print(f"Kaydedilecek '{KAYIT_KLASORU}' klasörü oluşturuldu.")

# --- 2. YARDIMCI FONKSİYONLAR ---

def load_and_resize_overlay(file_path, target_width, target_height):
    """
    PNG çerçeveyi PIL (Pillow) ile yükler, Alpha kanalını ayırır
    ve hedef boyuta yeniden boyutlandırır. (En güvenilir yöntem)
    """
    try:
        pil_img = Image.open(file_path).convert("RGBA")
    except Exception as e:
        print(f"Hata: Çerçeve yüklenemedi veya dönüştürülemedi: {e}")
        return None
    
    pil_img = pil_img.resize((target_width, target_height), Image.Resampling.LANCZOS)
    overlay_img = np.array(pil_img)
    
    r, g, b, a = cv2.split(overlay_img)
    overlay_img_bgra = cv2.merge((b, g, r, a))
    
    if overlay_img_bgra.shape[2] != 4:
        print("KRİTİK HATA: RGBA dönüşümü başarısız oldu!")
        return None

    return overlay_img_bgra


def overlay_transparent(background, overlay_bgra, x, y):
    """Şeffaf (alpha kanalı olan) bir görüntüyü arka plana bindirir."""
    h, w, _ = background.shape
    
    if overlay_bgra is None or overlay_bgra.shape[2] < 4:
        print("UYARI: Bindirme görüntüsünde Alpha kanalı yok. Atlanıyor.")
        return background.astype('uint8') 

    background_float = background.astype(float)
    overlay_float = overlay_bgra.astype(float) 

    overlay_bgr = overlay_float[:, :, :3]
    alpha = overlay_float[:, :, 3] / 255.0 

    bg_roi = background_float[y:y + h, x:x + w]
    bg_part = bg_roi * (1.0 - alpha[:, :, None])
    overlay_part = overlay_bgr * alpha[:, :, None]
    
    background_float[y:y + h, x:x + w] = bg_part + overlay_part
    
    return background_float.astype('uint8')


def generate_qr_code(url, size=300):
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=5, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    qr_opencv = cv2.cvtColor(np.array(img.convert('RGB')), cv2.COLOR_RGB2BGR)
    return cv2.resize(qr_opencv, (size, size))

def upload_photo_to_api(image, api_endpoint, api_key):
    is_success, buffer = cv2.imencode(".jpg", image)
    if not is_success:
        return None
    image_bytes = io.BytesIO(buffer)
    files = {'photo': ('topluluk_foto.jpg', image_bytes, 'image/jpeg')}
    data = {'api_key': api_key, 'timestamp': int(time.time())}
    try:
        response = requests.post(api_endpoint, files=files, data=data, timeout=10)
        response.raise_for_status() 
        result = response.json()
        if response.status_code == 200 and result.get('success') and result.get('download_url'):
            return result['download_url']
    except requests.exceptions.RequestException as e:
        print(f"API Bağlantı/İstek Hatası: {e}")
        return None
    return None

def is_hand_open(hand_landmarks):
    """Elin açık/kapalı olduğunu tespit eder (Basit Heuristik)"""
    if not hand_landmarks:
        return False
    
    # Parmak uçlarının bilekten (0) ne kadar uzakta olduğuna bakarız
    wrist_y = hand_landmarks.landmark[0].y
    
    # Eğer tüm parmak uçları (8, 12, 16, 20) bilekten belirgin şekilde yukarıdaysa (açık el)
    # MediaPipe el yönünü ters algılayabilir, bu yüzden bilekten küçük olup olmadığı kontrol edilir (yukarıda olması)
    is_open = all(hand_landmarks.landmark[i].y < wrist_y for i in [8, 12, 16, 20])
    
    return is_open

def is_hand_closed(hand_landmarks):
    """Elin kapalı (yumruk) olduğunu tespit eder."""
    if not hand_landmarks:
        return False
    
    # Yalnızca elin kapalı olduğunu (yumruk) tespit etmek için kullanılan basit bir yöntem
    # Parmak uçlarının (8, 12, 16, 20) dip boğumlarına (5, 9, 13, 17) göre aşağıda olup olmadığını kontrol eder.
    # Bu, elin kapalı olduğunu gösterir (Örneğin 8 < 6)
    is_closed = all(hand_landmarks.landmark[i].y > hand_landmarks.landmark[i - 3].y for i in [8, 12, 16, 20])
    
    return is_closed
# --- ANA DÖNGÜ VE İŞLEM ---

# YENİ DURUM DEĞİŞKENLERİ
SAYIM_SURESI = 3 # 3 saniye geri sayım
sayim_durumu = False
sayim_baslangici = 0
foto_cekildi = False 
cikis_sinyali = False 


with mp_face_detection.FaceDetection(
    model_selection=1, min_detection_confidence=0.5) as face_detection, \
    mp_hands.Hands(max_num_hands=2, min_detection_confidence=0.7) as hands: # GÜNCEL: İki eli de takip et

    # Kamerayı açmak için numaranızı deneyin (0, 1, 2,...)
    cap = cv2.VideoCapture(0) 

    if not cap.isOpened():
        print("Hata: Kamera açılamadı. Lütfen VideoCapture(0), (1) veya (2) deneyin.")
        exit()

    while cap.isOpened():
        success, image = cap.read()
        if not success:
            continue
        
        # Görüntü işlemede ortak adımlar
        image.flags.writeable = False
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        
        face_results = face_detection.process(image)
        hand_results = hands.process(image) 
        
        image.flags.writeable = True
        image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        
        h, w, _ = image.shape
        
        # HER DÖNGÜ BAŞINDA SIFIRLANAN DEĞİŞKENLER
        yuz_tespit_edildi = False
        eller_kapali_sayisi = 0 
        el_acik = False  # EKLENDİ: Artık tanımlı
        
        if face_results.detections:
            yuz_tespit_edildi = True

        if hand_results.multi_hand_landmarks:
            for hand_landmarks in hand_results.multi_hand_landmarks:
                mp_drawing.draw_landmarks(image, hand_landmarks, mp_hands.HAND_CONNECTIONS)
                
                # Çıkış kontrolü için kapalı el sayısını artır
                if is_hand_closed(hand_landmarks):
                    eller_kapali_sayisi += 1
                
                # Fotoğraf çekme kontrolü için açık el kontrolü
                if is_hand_open(hand_landmarks) and not sayim_durumu:
                    el_acik = True

        # --- ÇIKIŞ KONTROLÜ (İki Yumruk) ---
        if eller_kapali_sayisi == 2:
            cikis_sinyali = True
            cv2.putText(image, "UYGULAMA KAPATILIYOR...", (w // 2 - 250, h // 2), 
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2, cv2.LINE_AA)
            cv2.imshow('DevCam - Canli Akis', image)
            cv2.waitKey(2000) # 2 saniye bekleme
            break # Ana döngüyü kır ve çık

        
        # --- DURUM YÖNETİMİ (Çekim) ---
        
        # ÇEKİM BAŞLANGICI: Yüz varsa VE el açık işaretini almışsak
        if not sayim_durumu and yuz_tespit_edildi and el_acik:
            sayim_durumu = True
            sayim_baslangici = time.time()
            cv2.putText(image, "SAYIM BASLADI! YUMRUK YAPARAK DURDUR", (w // 2 - 350, 80), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 0, 0), 2, cv2.LINE_AA)
            
        elif sayim_durumu:
            # Geri sayım devam ediyor
            gecen_sure = time.time() - sayim_baslangici
            kalan_sure = SAYIM_SURESI - gecen_sure
            
            if kalan_sure > 0:
                # Geri sayım metni
                sayim_yazisi = f"{int(kalan_sure) + 1}..."
                
                # Merkezi ekrana büyük fontla sayımı yaz
                cv2.putText(image, sayim_yazisi, (w // 2 - 100, h // 2), 
                            cv2.FONT_HERSHEY_SIMPLEX, 4, (0, 255, 255), 8, cv2.LINE_AA)
                
                # Eğer herhangi bir el kapalıysa sayımı durdur
                if eller_kapali_sayisi > 0:
                    sayim_durumu = False
                    cv2.putText(image, "SAYIM DURDU! TEKRAR AC", (w // 2 - 300, 80), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2, cv2.LINE_AA)
                    
            else:
                # SÜRE DOLDU: Fotoğraf çekimi tetikle!
                foto_cekildi = True
                sayim_durumu = False

        else:
            # Varsayılan talimatlar
            if yuz_tespit_edildi:
                cv2.putText(image, "POZ VERIN! (Elini Ac)", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2, cv2.LINE_AA)
            else:
                cv2.putText(image, "Kameraya Bakin...", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2, cv2.LINE_AA)


        # Canlı akışı DevCam başlığıyla göster
        cv2.imshow('DevCam - Canli Akis', image)

        # --- FOTOĞRAF ÇEKME VE API İŞLEMİ ANII ---
        key = cv2.waitKey(5) & 0xFF
        if foto_cekildi: # El hareketi ile tetiklendi

            cerceve_img = load_and_resize_overlay("cerceve.png", w, h)
            
            if cerceve_img is not None:
                # islenmis_foto sadece burada kullanılıyor, canlı akıştaki 'POZ VERİN' metni buraya gelmez
                islenmis_foto = overlay_transparent(image.copy(), cerceve_img, 0, 0)
                
                rastgele_slogan = random.choice(SLOGANLAR)
                slogan_gosterimi = rastgele_slogan.replace('ğ', 'g').replace('ı', 'i').replace('ş', 's').replace('ü', 'u').replace('ö', 'o').replace('ç', 'c')
                
                text_size = cv2.getTextSize(slogan_gosterimi, cv2.FONT_HERSHEY_SIMPLEX, 1, 2)[0]
                text_x = (w - text_size[0]) // 2 
                text_y = h - 30 
                
                cv2.putText(islenmis_foto, slogan_gosterimi, (text_x, text_y), 
                            cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2, cv2.LINE_AA)
                
                # --- API Entegrasyonu ---
                print("API'ye YÜKLENİYOR... Lütfen bekleyin.")
                download_url = upload_photo_to_api(islenmis_foto, API_ENDPOINT, API_KEY)
                
                if download_url:
                    # Başarılı QR Kod Gösterimi
                    print(f"BAŞARILI: İndirme Linki Alındı: {download_url}")
                    qr_img = generate_qr_code(download_url)
                    
                    cv2.imshow('SONUC', islenmis_foto) 
                    cv2.imshow('QR KODU - TELEFONLA OKUTUN', qr_img)
                    
                    # 15 saniye bekle
                    cv2.waitKey(15000) 
                    cv2.destroyWindow('SONUC')
                    cv2.destroyWindow('QR KODU - TELEFONLA OKUTUN')
                
                else:
                    # YEDEKLEME (API başarısız olursa)
                    timestamp = int(time.time())
                    kayit_adi = f"{KAYIT_KLASORU}/API_HATALI_YEDEK_{timestamp}.jpg"
                    cv2.imwrite(kayit_adi, islenmis_foto) 
                    print(f"UYARI: API Başarısız. Fotoğraf YEDEK OLARAK kaydedildi: {kayit_adi}")
                    
                    cv2.putText(image, "API HATA! YEDEK KAYIT YAPILDI.", (50, 100), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 3, cv2.LINE_AA)
                    cv2.imshow('DevCam - Canli Akis', image)
                    cv2.waitKey(3000)
            
            # Çekim durumunu sıfırla
            foto_cekildi = False


        # 'Q' tuşuna basıldığında döngüyü kır (Klavye yedek olarak hala çalışır)
        if key == ord('q'):
            break

    # Kaynakları serbest bırak
    cap.release()
    cv2.destroyAllWindows()
