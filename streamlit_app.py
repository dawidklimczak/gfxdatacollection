import streamlit as st
import json
import hashlib
import io
import tempfile
from datetime import datetime
from PIL import Image
import pandas as pd
from colorthief import ColorThief
from math import gcd
import base64
import time

# Google Drive API
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from googleapiclient.errors import HttpError
import requests

# Konfiguracja aplikacji
st.set_page_config(
    page_title="Katalog Grafik",
    page_icon="🎨",
    layout="wide"
)

def retry_api_call(func, max_retries=3, delay=1):
    """Retry mechanism dla Google API calls"""
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            error_str = str(e).lower()
            if attempt == max_retries - 1:
                raise e
            
            if any(keyword in error_str for keyword in ['ssl', 'timeout', 'connection', 'network']):
                st.warning(f"Próba {attempt + 1}/{max_retries} nie powiodła się. Ponawiam...")
                time.sleep(delay * (attempt + 1))
                continue
            else:
                raise e

@st.cache_resource
def connect_to_drive():
    """Łączy się z Google Drive API z cache"""
    try:
        credentials = service_account.Credentials.from_service_account_info(
            st.secrets["google_service_account"],
            scopes=['https://www.googleapis.com/auth/drive']
        )
        service = build('drive', 'v3', credentials=credentials)
        return service
    except Exception as e:
        st.error(f"Błąd połączenia z Google Drive: {e}")
        return None

def connect_to_drive_uploader():
    """Łączy się z Google Drive API bez cache (dla uploadera)"""
    try:
        credentials = service_account.Credentials.from_service_account_info(
            st.secrets["google_service_account"],
            scopes=['https://www.googleapis.com/auth/drive']
        )
        service = build('drive', 'v3', credentials=credentials)
        return service
    except Exception as e:
        st.error(f"Błąd połączenia z Google Drive: {e}")
        return None

def get_folder_id():
    """Pobiera ID głównego folderu z secrets"""
    if "google_service_account" in st.secrets:
        if "drive_folder_id" in st.secrets["google_service_account"]:
            return st.secrets["google_service_account"]["drive_folder_id"]
    return st.secrets.get("drive_folder_id", "")

def test_drive_access(service, folder_id):
    """Testuje dostęp do folderu Google Drive"""
    try:
        folder = service.files().get(fileId=folder_id).execute()
        return True, f"✅ Dostęp OK. Folder: {folder.get('name', 'Bez nazwy')}"
    except Exception as e:
        return False, f"❌ Błąd dostępu: {str(e)}"

def find_or_create_folder(service, parent_folder_id, folder_name):
    """Znajduje lub tworzy folder o podanej nazwie"""
    query = f"name='{folder_name}' and '{parent_folder_id}' in parents and mimeType='application/vnd.google-apps.folder'"
    results = service.files().list(q=query).execute()
    items = results.get('files', [])
    
    if items:
        return items[0]['id']
    
    folder_metadata = {
        'name': folder_name,
        'parents': [parent_folder_id],
        'mimeType': 'application/vnd.google-apps.folder'
    }
    folder = service.files().create(body=folder_metadata).execute()
    return folder['id']

def upload_file_to_drive(service, file_content, filename, parent_folder_id, mime_type='image/jpeg'):
    """Upload pliku na Google Drive"""
    try:
        media = MediaIoBaseUpload(io.BytesIO(file_content), mimetype=mime_type)
        file_metadata = {
            'name': filename,
            'parents': [parent_folder_id]
        }
        file = service.files().create(body=file_metadata, media_body=media).execute()
        return file['id']
    except Exception as e:
        st.error(f"Błąd uploadu pliku {filename}: {e}")
        return None

def download_file_from_drive(service, file_id):
    """Pobiera plik z Google Drive"""
    try:
        request = service.files().get_media(fileId=file_id)
        file_io = io.BytesIO()
        downloader = MediaIoBaseDownload(file_io, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()
        file_io.seek(0)
        return file_io.getvalue()
    except Exception as e:
        st.error(f"Błąd pobierania pliku: {e}")
        return None

def find_file_in_folder(service, folder_id, filename):
    """Znajduje plik w folderze"""
    query = f"name='{filename}' and '{folder_id}' in parents"
    results = service.files().list(q=query).execute()
    items = results.get('files', [])
    return items[0]['id'] if items else None

def save_json_to_drive(service, data, folder_id, filename="graphics_data.json"):
    """Zapisuje JSON na Google Drive"""
    try:
        existing_file_id = find_file_in_folder(service, folder_id, filename)
        if existing_file_id:
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            backup_filename = f"graphics_data_backup_{timestamp}.json"
            
            existing_content = download_file_from_drive(service, existing_file_id)
            if existing_content:
                backups_folder_id = find_or_create_folder(service, folder_id, "backups")
                upload_file_to_drive(service, existing_content, backup_filename, backups_folder_id, 'application/json')
        
        json_content = json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8')
        media = MediaIoBaseUpload(io.BytesIO(json_content), mimetype='application/json')
        
        if existing_file_id:
            service.files().update(fileId=existing_file_id, media_body=media).execute()
        else:
            file_metadata = {
                'name': filename,
                'parents': [folder_id]
            }
            service.files().create(body=file_metadata, media_body=media).execute()
        
        return True
    except Exception as e:
        st.error(f"Błąd zapisu JSON: {e}")
        return False

def load_json_from_drive(service, folder_id, filename="graphics_data.json"):
    """Ładuje JSON z Google Drive"""
    try:
        file_id = find_file_in_folder(service, folder_id, filename)
        if not file_id:
            return {"graphics": []}
        
        content = download_file_from_drive(service, file_id)
        if content:
            return json.loads(content.decode('utf-8'))
        return {"graphics": []}
    except Exception as e:
        st.error(f"Błąd odczytu JSON: {e}")
        return {"graphics": []}

def calculate_ratio(width, height):
    """Oblicza najbliższą standardową proporcję obrazu"""
    actual_ratio = width / height
    
    standard_ratios = {
        "1:1": 1.0,
        "5:4": 1.25,
        "4:3": 1.333,
        "3:2": 1.5,
        "16:10": 1.6,
        "16:9": 1.778,
        "2:1": 2.0,
        "4:5": 0.8,
        "3:4": 0.75,
        "2:3": 0.667,
        "10:16": 0.625,
        "9:16": 0.5625,
        "1:2": 0.5
    }
    
    closest_ratio = min(standard_ratios.items(), 
                       key=lambda x: abs(x[1] - actual_ratio))
    
    return closest_ratio[0]

def extract_color_palette(image_bytes, num_colors=6):
    """Wyciąga paletę kolorów z obrazu"""
    try:
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp_file:
            tmp_file.write(image_bytes)
            tmp_file_path = tmp_file.name
        
        color_thief = ColorThief(tmp_file_path)
        palette = color_thief.get_palette(color_count=num_colors)
        
        import os
        os.unlink(tmp_file_path)
        
        hex_colors = [f"#{r:02x}{g:02x}{b:02x}" for r, g, b in palette]
        return hex_colors
    except Exception as e:
        st.warning(f"Nie udało się wyciągnąć palety kolorów: {e}")
        return []

def process_uploaded_image(service, uploaded_file, images_folder_id):
    """Przetwarza przesłany obraz i zapisuje na Drive"""
    file_bytes = uploaded_file.getvalue()
    file_hash = hashlib.md5(file_bytes).hexdigest()
    
    image = Image.open(io.BytesIO(file_bytes))
    
    file_extension = uploaded_file.name.split('.')[-1].lower()
    filename = f"{file_hash}.{file_extension}"
    
    drive_file_id = upload_file_to_drive(service, file_bytes, filename, images_folder_id)
    
    if not drive_file_id:
        return None
    
    width, height = image.size
    ratio = calculate_ratio(width, height)
    color_palette = extract_color_palette(file_bytes)
    
    return {
        "id": file_hash,
        "filename": uploaded_file.name,
        "drive_file_id": drive_file_id,
        "stored_filename": filename,
        "upload_date": datetime.now().isoformat(),
        "technical": {
            "format": image.format or file_extension.upper(),
            "dimensions": [width, height],
            "ratio": ratio,
            "file_size": len(file_bytes),
            "color_palette": color_palette
        }
    }

def get_image_from_drive(service, file_id):
    """Pobiera obraz z Google Drive"""
    return download_file_from_drive(service, file_id)

def uploader_page():
    st.title("Dodaj Nową Grafikę")
    
    if not st.session_state.get("authenticated", False):
        st.subheader("🔒 Dostęp ograniczony")
        st.info("Podaj hasło aby uzyskać dostęp do dodawania grafik.")
        
        password = st.text_input("Hasło", type="password")
        if st.button("Zaloguj"):
            correct_password = st.secrets.get("uploader_password", "")
            if not correct_password and "google_service_account" in st.secrets:
                correct_password = st.secrets["google_service_account"].get("uploader_password", "")
            
            if password and correct_password and password == correct_password:
                st.session_state["authenticated"] = True
                st.success("✅ Zalogowano pomyślnie!")
                st.rerun()
            elif not correct_password:
                st.error("❌ Hasło nie zostało skonfigurowane w secrets!")
            else:
                st.error("❌ Nieprawidłowe hasło!")
        return
    
    if st.sidebar.button("🔓 Wyloguj z uploadera"):
        st.session_state["authenticated"] = False
        st.rerun()
    
    service = connect_to_drive_uploader()
    if not service:
        st.error("Brak połączenia z Google Drive!")
        return
    
    main_folder_id = get_folder_id()
    if not main_folder_id:
        st.error("Brak ID folderu głównego w konfiguracji!")
        return
    
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.subheader("Plik graficzny")
        uploaded_file = st.file_uploader(
            "Wybierz plik graficzny",
            type=['png', 'jpg', 'jpeg', 'webp', 'gif'],
            help="Obsługiwane formaty: PNG, JPG, JPEG, WEBP, GIF"
        )
        
        if uploaded_file:
            st.image(uploaded_file, caption="Podgląd", use_container_width=True)
    
    with col2:
        st.subheader("Dane biznesowe")
        
        numer_akcji = st.text_input("Numer akcji", help="Unikalny numer akcji/kampanii")
        
        rynek = st.selectbox(
            "Rynek",
            options=["medica", "edukacja", "biznes"],
            index=0
        )
        
        typ_odbiorcy = st.selectbox(
            "Typ odbiorcy",
            options=["cold", "warm", "look-a-like", "remarketing"],
            index=0
        )
        
        typ_kampanii = st.selectbox(
            "Typ kampanii",
            options=["sales", "traffic", "leads", "reach", "awareness"],
            index=0
        )
        
        col2_1, col2_2 = st.columns(2)
        with col2_1:
            ctr = st.number_input("CTR (%)", min_value=0.0, step=0.01, format="%.2f")
        with col2_2:
            roas = st.number_input("ROAS", min_value=0.0, step=0.01, format="%.2f")
    
    if st.button("Dodaj grafikę", type="primary"):
        if uploaded_file and numer_akcji:
            try:
                with st.spinner("Przetwarzanie i upload na Google Drive..."):
                    images_folder_id = retry_api_call(
                        lambda: find_or_create_folder(service, main_folder_id, "images")
                    )
                    
                    image_data = retry_api_call(
                        lambda: process_uploaded_image(service, uploaded_file, images_folder_id)
                    )
                    
                    if not image_data:
                        st.error("Błąd podczas uploadu obrazu na Google Drive!")
                        return
                    
                    image_data["business"] = {
                        "numer_akcji": numer_akcji,
                        "rynek": rynek,
                        "typ_odbiorcy": typ_odbiorcy,
                        "typ_kampanii": typ_kampanii,
                        "ctr": ctr,
                        "roas": roas
                    }
                    
                    data = retry_api_call(
                        lambda: load_json_from_drive(service, main_folder_id)
                    )
                    
                    existing_ids = [item["id"] for item in data["graphics"]]
                    if image_data["id"] in existing_ids:
                        st.warning("Ta grafika już istnieje w bazie!")
                        return
                    
                    data["graphics"].append(image_data)
                    
                    success = retry_api_call(
                        lambda: save_json_to_drive(service, data, main_folder_id)
                    )
                    
                    if success:
                        st.success("Grafika została dodana!")
                        st.balloons()
                        st.cache_data.clear()
                    else:
                        st.error("Wystąpił błąd podczas zapisu.")
                        
            except Exception as e:
                st.error(f"Błąd podczas przetwarzania: {e}")
        else:
            st.error("Wypełnij wszystkie wymagane pola (plik graficzny i numer akcji)!")

def report_page():
    st.title("Raport Grafik")
    
    service = connect_to_drive()
    if not service:
        st.error("Brak połączenia z Google Drive!")
        return
    
    main_folder_id = get_folder_id()
    if not main_folder_id:
        st.error("Brak ID folderu głównego w konfiguracji!")
        return
    
    with st.spinner("Ładowanie danych z Google Drive..."):
        data = load_json_from_drive(service, main_folder_id)
        graphics = data["graphics"]
    
    if not graphics:
        st.info("Brak grafik w bazie. Dodaj pierwszą grafikę w zakładce 'Uploader'.")
        return
    
    st.subheader("Filtry")
    col1, col2, col3 = st.columns(3)
    
    rynki = list(set([g["business"]["rynek"] for g in graphics]))
    typy_odbiorcy = list(set([g["business"]["typ_odbiorcy"] for g in graphics]))
    typy_kampanii = list(set([g["business"]["typ_kampanii"] for g in graphics]))
    
    with col1:
        selected_rynek = st.multiselect("Rynek", options=rynki, default=rynki)
    with col2:
        selected_typ_odbiorcy = st.multiselect("Typ odbiorcy", options=typy_odbiorcy, default=typy_odbiorcy)
    with col3:
        selected_typ_kampanii = st.multiselect("Typ kampanii", options=typy_kampanii, default=typy_kampanii)
    
    sort_col1, sort_col2 = st.columns(2)
    with sort_col1:
        sort_by = st.selectbox("Sortuj według", ["upload_date", "ctr", "roas", "filename", "numer_akcji"])
    with sort_col2:
        sort_order = st.selectbox("Kolejność", ["Malejąco", "Rosnąco"])
    
    filtered_graphics = [
        g for g in graphics 
        if (g["business"]["rynek"] in selected_rynek and
            g["business"]["typ_odbiorcy"] in selected_typ_odbiorcy and
            g["business"]["typ_kampanii"] in selected_typ_kampanii)
    ]
    
    reverse = sort_order == "Malejąco"
    if sort_by in ["ctr", "roas"]:
        filtered_graphics.sort(key=lambda x: x["business"][sort_by], reverse=reverse)
    elif sort_by == "upload_date":
        filtered_graphics.sort(key=lambda x: x["upload_date"], reverse=reverse)
    elif sort_by == "numer_akcji":
        filtered_graphics.sort(key=lambda x: x["business"].get("numer_akcji", ""), reverse=reverse)
    else:
        filtered_graphics.sort(key=lambda x: x["filename"], reverse=reverse)
    
    st.subheader(f"Znaleziono: {len(filtered_graphics)} grafik")
    
    if filtered_graphics:
        avg_ctr = sum([g["business"]["ctr"] for g in filtered_graphics]) / len(filtered_graphics)
        avg_roas = sum([g["business"]["roas"] for g in filtered_graphics]) / len(filtered_graphics)
        
        metric_col1, metric_col2 = st.columns(2)
        with metric_col1:
            st.metric("Średni CTR", f"{avg_ctr:.2f}%")
        with metric_col2:
            st.metric("Średni ROAS", f"{avg_roas:.2f}")
        
        st.subheader("Grafiki")
        
        header_cols = st.columns([1, 1.5, 2, 2, 1, 1, 1.5, 1, 2])
        header_cols[0].write("**Grafika**")
        header_cols[1].write("**Numer akcji**")
        header_cols[2].write("**Typ odbiorcy**")
        header_cols[3].write("**Typ kampanii**")
        header_cols[4].write("**CTR**")
        header_cols[5].write("**ROAS**")
        header_cols[6].write("**Wymiary**")
        header_cols[7].write("**Proporcje**")
        header_cols[8].write("**Paleta kolorów**")
        
        st.divider()
        
        for idx, graphic in enumerate(filtered_graphics):
            cols = st.columns([1, 1.5, 2, 2, 1, 1, 1.5, 1, 2])
            
            with cols[0]:
                if graphic.get("drive_file_id"):
                    try:
                        with st.spinner("Ładowanie..."):
                            image_data = get_image_from_drive(service, graphic["drive_file_id"])
                        
                        if image_data:
                            image = Image.open(io.BytesIO(image_data))
                            st.image(image, use_container_width=True)
                        else:
                            st.write("❌ Brak danych")
                            st.caption("Nie udało się pobrać")
                    except Exception as e:
                        st.write("❌ Błąd")
                        st.caption(f"Error: {str(e)[:30]}...")
                else:
                    st.write("❌ Brak ID")
                    st.caption("Brak drive_file_id")
            
            with cols[1]:
                numer_akcji = graphic['business'].get('numer_akcji', 'Brak')
                st.write(numer_akcji)
            
            with cols[2]:
                st.write(graphic['business']['typ_odbiorcy'])
            
            with cols[3]:
                st.write(graphic['business']['typ_kampanii'])
            
            with cols[4]:
                st.write(f"{graphic['business']['ctr']:.2f}%")
            
            with cols[5]:
                st.write(f"{graphic['business']['roas']:.2f}")
            
            with cols[6]:
                tech = graphic['technical']
                st.write(f"{tech['dimensions'][0]}×{tech['dimensions'][1]}")
            
            with cols[7]:
                st.write(tech['ratio'])
            
            with cols[8]:
                if tech['color_palette']:
                    colors_html = "".join([
                        f'<span style="display:inline-block;width:20px;height:20px;background-color:{color};margin:1px;border:1px solid #ddd;border-radius:2px;" title="{color}"></span>' 
                        for color in tech['color_palette'][:6]
                    ])
                    st.markdown(colors_html, unsafe_allow_html=True)
                else:
                    st.write("-")
            
            if idx < len(filtered_graphics) - 1:
                st.write("")

def main():
    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False
    
    st.sidebar.title("Katalog Grafik")
    
    if st.session_state.get("authenticated", False):
        st.sidebar.success("🔓 Zalogowano do uploadera")
    else:
        st.sidebar.info("🔒 Uploader wymaga hasła")
    
    page = st.sidebar.radio("Wybierz stronę", ["Raport", "Uploader"], index=0)
    
    if page == "Uploader":
        service = connect_to_drive_uploader()
    else:
        service = connect_to_drive()
        
    if service:
        st.sidebar.success("✅ Połączono z Google Drive")
        folder_id = get_folder_id()
        if folder_id:
            st.sidebar.info(f"📁 Folder: {folder_id[:8]}...")
            
            access_ok, access_msg = test_drive_access(service, folder_id)
            if access_ok:
                st.sidebar.success(access_msg)
            else:
                st.sidebar.error(access_msg)
    else:
        st.sidebar.error("❌ Brak połączenia z Google Drive")
    
    if page == "Raport":
        report_page()
    elif page == "Uploader":
        uploader_page()

if __name__ == "__main__":
    main()