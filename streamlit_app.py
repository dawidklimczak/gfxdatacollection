import streamlit as st
import json
import os
import hashlib
import shutil
from datetime import datetime
from PIL import Image
import pandas as pd
from colorthief import ColorThief
import io
import tempfile
from math import gcd

# Konfiguracja aplikacji
st.set_page_config(
    page_title="Katalog Grafik",
    page_icon="🎨",
    layout="wide"
)

# Tworzenie struktury folderów
def create_directories():
    """Tworzy niezbędne foldery jeśli nie istnieją"""
    os.makedirs("data", exist_ok=True)
    os.makedirs("data/uploads", exist_ok=True)
    os.makedirs("backups", exist_ok=True)

# Funkcje pomocnicze dla JSON
def load_data():
    """Ładuje dane z pliku JSON"""
    try:
        with open("data/graphics_data.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"graphics": []}
    except json.JSONDecodeError:
        st.error("Błąd odczytu pliku danych. Sprawdź backup.")
        return {"graphics": []}

def save_data(data):
    """Zapisuje dane do pliku JSON z backupem"""
    # Tworzenie backupu przed zapisem
    if os.path.exists("data/graphics_data.json"):
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        backup_path = f"backups/graphics_data_{timestamp}.json"
        shutil.copy2("data/graphics_data.json", backup_path)
    
    # Atomowy zapis przez plik tymczasowy
    temp_path = "data/graphics_data_temp.json"
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        # Przeniesienie pliku tymczasowego na docelowy
        shutil.move(temp_path, "data/graphics_data.json")
        return True
    except Exception as e:
        st.error(f"Błąd zapisu danych: {e}")
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return False

def calculate_ratio(width, height):
    """Oblicza proporcje obrazu"""
    ratio_gcd = gcd(width, height)
    ratio_w = width // ratio_gcd
    ratio_h = height // ratio_gcd
    
    # Popularne proporcje
    common_ratios = {
        (1, 1): "1:1",
        (4, 3): "4:3", 
        (3, 4): "3:4",
        (16, 9): "16:9",
        (9, 16): "9:16",
        (3, 2): "3:2",
        (2, 3): "2:3",
        (5, 4): "5:4",
        (4, 5): "4:5"
    }
    
    return common_ratios.get((ratio_w, ratio_h), f"{ratio_w}:{ratio_h}")

def extract_color_palette(image_bytes, num_colors=6):
    """Wyciąga paletę kolorów z obrazu"""
    try:
        # Zapisz obraz do pliku tymczasowego
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp_file:
            tmp_file.write(image_bytes)
            tmp_file_path = tmp_file.name
        
        # Wyciągnij paletę kolorów
        color_thief = ColorThief(tmp_file_path)
        palette = color_thief.get_palette(color_count=num_colors)
        
        # Usuń plik tymczasowy
        os.unlink(tmp_file_path)
        
        # Konwertuj na hex
        hex_colors = [f"#{r:02x}{g:02x}{b:02x}" for r, g, b in palette]
        return hex_colors
    except Exception as e:
        st.warning(f"Nie udało się wyciągnąć palety kolorów: {e}")
        return []

def process_uploaded_image(uploaded_file):
    """Przetwarza przesłany obraz i wyciąga metadane"""
    # Generuj unikalny hash
    file_bytes = uploaded_file.getvalue()
    file_hash = hashlib.md5(file_bytes).hexdigest()
    
    # Otwórz obraz
    image = Image.open(io.BytesIO(file_bytes))
    
    # Zapisz obraz na dysku
    file_extension = uploaded_file.name.split('.')[-1].lower()
    filename = f"{file_hash}.{file_extension}"
    filepath = f"data/uploads/{filename}"
    
    with open(filepath, "wb") as f:
        f.write(file_bytes)
    
    # Wyciągnij metadane
    width, height = image.size
    ratio = calculate_ratio(width, height)
    color_palette = extract_color_palette(file_bytes)
    
    return {
        "id": file_hash,
        "filename": uploaded_file.name,
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

# Strona 1: Uploader
def uploader_page():
    st.title("Dodaj Nową Grafikę")
    
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
        
        rynek = st.selectbox(
            "Rynek",
            options=["medica", "edukacja", "biznes"],
            index=0
        )
        
        typ_odbiorcy = st.text_input("Typ odbiorcy")
        typ_kampanii = st.text_input("Typ kampanii")
        
        col2_1, col2_2 = st.columns(2)
        with col2_1:
            ctr = st.number_input("CTR (%)", min_value=0.0, step=0.01, format="%.2f")
        with col2_2:
            roas = st.number_input("ROAS", min_value=0.0, step=0.01, format="%.2f")
    
    if st.button("Dodaj grafikę", type="primary"):
        if uploaded_file and typ_odbiorcy and typ_kampanii:
            try:
                # Przetwórz obraz
                image_data = process_uploaded_image(uploaded_file)
                
                # Dodaj dane biznesowe
                image_data["business"] = {
                    "rynek": rynek,
                    "typ_odbiorcy": typ_odbiorcy,
                    "typ_kampanii": typ_kampanii,
                    "ctr": ctr,
                    "roas": roas
                }
                
                # Wczytaj istniejące dane
                data = load_data()
                
                # Sprawdź duplikaty
                existing_ids = [item["id"] for item in data["graphics"]]
                if image_data["id"] in existing_ids:
                    st.warning("Ta grafika już istnieje w bazie!")
                    return
                
                # Dodaj nową grafikę
                data["graphics"].append(image_data)
                
                # Zapisz dane
                if save_data(data):
                    st.success("Grafika została dodana!")
                    st.balloons()
                else:
                    st.error("Wystąpił błąd podczas zapisu.")
                    
            except Exception as e:
                st.error(f"Błąd podczas przetwarzania: {e}")
        else:
            st.error("Wypełnij wszystkie wymagane pola!")

# Strona 2: Raport
def report_page():
    st.title("Raport Grafik")
    
    # Wczytaj dane
    data = load_data()
    graphics = data["graphics"]
    
    if not graphics:
        st.info("Brak grafik w bazie. Dodaj pierwszą grafikę w zakładce 'Uploader'.")
        return
    
    # Filtry
    st.subheader("Filtry")
    col1, col2, col3 = st.columns(3)
    
    # Pobierz unikalne wartości do filtrów
    rynki = list(set([g["business"]["rynek"] for g in graphics]))
    typy_odbiorcy = list(set([g["business"]["typ_odbiorcy"] for g in graphics]))
    typy_kampanii = list(set([g["business"]["typ_kampanii"] for g in graphics]))
    
    with col1:
        selected_rynek = st.multiselect("Rynek", options=rynki, default=rynki)
    with col2:
        selected_typ_odbiorcy = st.multiselect("Typ odbiorcy", options=typy_odbiorcy, default=typy_odbiorcy)
    with col3:
        selected_typ_kampanii = st.multiselect("Typ kampanii", options=typy_kampanii, default=typy_kampanii)
    
    # Sortowanie
    sort_col1, sort_col2 = st.columns(2)
    with sort_col1:
        sort_by = st.selectbox("Sortuj według", ["upload_date", "ctr", "roas", "filename"])
    with sort_col2:
        sort_order = st.selectbox("Kolejność", ["Malejąco", "Rosnąco"])
    
    # Filtruj dane
    filtered_graphics = [
        g for g in graphics 
        if (g["business"]["rynek"] in selected_rynek and
            g["business"]["typ_odbiorcy"] in selected_typ_odbiorcy and
            g["business"]["typ_kampanii"] in selected_typ_kampanii)
    ]
    
    # Sortuj dane
    reverse = sort_order == "Malejąco"
    if sort_by in ["ctr", "roas"]:
        filtered_graphics.sort(key=lambda x: x["business"][sort_by], reverse=reverse)
    elif sort_by == "upload_date":
        filtered_graphics.sort(key=lambda x: x["upload_date"], reverse=reverse)
    else:
        filtered_graphics.sort(key=lambda x: x["filename"], reverse=reverse)
    
    # Pokaż statystyki
    st.subheader(f"Znaleziono: {len(filtered_graphics)} grafik")
    
    if filtered_graphics:
        # Statystyki podsumowujące
        avg_ctr = sum([g["business"]["ctr"] for g in filtered_graphics]) / len(filtered_graphics)
        avg_roas = sum([g["business"]["roas"] for g in filtered_graphics]) / len(filtered_graphics)
        
        metric_col1, metric_col2 = st.columns(2)
        with metric_col1:
            st.metric("Średni CTR", f"{avg_ctr:.2f}%")
        with metric_col2:
            st.metric("Średni ROAS", f"{avg_roas:.2f}")
        
        # Tabela z grafikami
        st.subheader("Grafiki")
        
        # Nagłówki tabeli
        header_cols = st.columns([1, 2, 2, 1, 1, 1.5, 1, 2])
        header_cols[0].write("**Grafika**")
        header_cols[1].write("**Typ odbiorcy**")
        header_cols[2].write("**Typ kampanii**")
        header_cols[3].write("**CTR**")
        header_cols[4].write("**ROAS**")
        header_cols[5].write("**Wymiary**")
        header_cols[6].write("**Proporcje**")
        header_cols[7].write("**Paleta kolorów**")
        
        st.divider()
        
        # Wiersze tabeli
        for idx, graphic in enumerate(filtered_graphics):
            cols = st.columns([1, 2, 2, 1, 1, 1.5, 1, 2])
            
            with cols[0]:
                # Miniaturka
                image_path = f"data/uploads/{graphic['stored_filename']}"
                if os.path.exists(image_path):
                    st.image(image_path, width=60)
                    # Przycisk do powiększenia
                    if st.button("🔍", key=f"enlarge_{graphic['id']}", help="Powiększ grafikę"):
                        st.image(image_path, caption=graphic['filename'])
                else:
                    st.write("❌")
            
            with cols[1]:
                st.write(graphic['business']['typ_odbiorcy'])
            
            with cols[2]:
                st.write(graphic['business']['typ_kampanii'])
            
            with cols[3]:
                st.write(f"{graphic['business']['ctr']:.2f}%")
            
            with cols[4]:
                st.write(f"{graphic['business']['roas']:.2f}")
            
            with cols[5]:
                tech = graphic['technical']
                st.write(f"{tech['dimensions'][0]}×{tech['dimensions'][1]}")
            
            with cols[6]:
                st.write(tech['ratio'])
            
            with cols[7]:
                # Paleta kolorów jako małe kwadraciki
                if tech['color_palette']:
                    colors_html = "".join([
                        f'<span style="display:inline-block;width:20px;height:20px;background-color:{color};margin:1px;border:1px solid #ddd;border-radius:2px;" title="{color}"></span>' 
                        for color in tech['color_palette'][:6]  # Max 6 kolorów
                    ])
                    st.markdown(colors_html, unsafe_allow_html=True)
                else:
                    st.write("-")
            
            # Separator między wierszami
            if idx < len(filtered_graphics) - 1:
                st.write("")

# Główna aplikacja
def main():
    create_directories()
    
    # Sidebar z nawigacją
    st.sidebar.title("Katalog Grafik")
    page = st.sidebar.selectbox("Wybierz stronę", ["Uploader", "Raport"])
    
    # Informacje o backupach
    backup_files = [f for f in os.listdir("backups") if f.startswith("graphics_data_")]
    if backup_files:
        st.sidebar.write(f"Dostępne backupy: {len(backup_files)}")
        if st.sidebar.button("Pokaż backupy"):
            st.sidebar.write("Ostatnie backupy:")
            for backup in sorted(backup_files)[-5:]:
                st.sidebar.text(backup)
    
    # Wybór strony
    if page == "Uploader":
        uploader_page()
    elif page == "Raport":
        report_page()

if __name__ == "__main__":
    main()