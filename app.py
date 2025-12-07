import streamlit as st
import os
import json
import base64
import io
import zipfile
from datetime import datetime
from typing import List, Optional, Dict, Any
from google import genai
from google.genai import types
from PIL import Image
from fpdf import FPDF
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# Configuración de página
st.set_page_config(
    page_title="AlbaFactura AI",
    page_icon="🧾",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 1. MODELOS DE DATOS Y PERSISTENCIA ---

FILES_DIR = "data"
SETTINGS_FILE = os.path.join(FILES_DIR, "settings.json")
CLIENTS_FILE = os.path.join(FILES_DIR, "clients.json")

# Asegurar que existe el directorio
os.makedirs(FILES_DIR, exist_ok=True)

DEFAULT_SETTINGS = {
    "name": "",
    "cif": "",
    "address": "",
    "defaultTaxRate": 21,
    "logo_path": None 
}

def load_json(filepath, default):
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return default
    return default

def save_json(filepath, data):
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# Cargar estado inicial
if 'settings' not in st.session_state:
    st.session_state.settings = load_json(SETTINGS_FILE, DEFAULT_SETTINGS)
if 'clients' not in st.session_state:
    st.session_state.clients = load_json(CLIENTS_FILE, [])
if 'processed_invoices' not in st.session_state:
    st.session_state.processed_invoices = []
if 'current_invoice_index' not in st.session_state:
    st.session_state.current_invoice_index = 0

# --- 2. SERVICIOS (GEMINI & PDF) ---

def get_gemini_client():
    api_key = os.environ.get("API_KEY")
    if not api_key:
        st.error("⚠️ No se ha encontrado la API Key. Configura la variable de entorno API_KEY.")
        return None
    return genai.Client(api_key=api_key)

def process_invoice_with_gemini(file_bytes, mime_type, filename):
    client = get_gemini_client()
    if not client:
        return None

    prompt = """
      Actúa como un sistema experto en digitalización de documentos administrativos.
      Analiza el archivo adjunto (albarán/nota de entrega).
      
      OBJETIVO: Extraer datos para convertir este ALBARÁN en FACTURA.
      
      CAMPOS A EXTRAER (JSON):
      - invoiceNumber: Número de Albarán/Referencia.
      - date: Fecha de emisión (YYYY-MM-DD).
      - dueDate: Fecha vencimiento (opcional).
      - supplierName: Emisor (Proveedor).
      - supplierAddress: Dirección proveedor.
      - clientName: Cliente receptor.
      - clientCif: CIF/NIF del cliente.
      - clientAddress: Dirección cliente.
      - items: Array de objetos {description, quantity, unitPrice, total}.
        * Si unitPrice no aparece, intenta inferirlo o pon 0.
      - subtotal: Suma de totales.
      - taxRate: % IVA (defecto 21).
      - taxAmount: Cantidad IVA.
      - total: Total final.
      - notes: Observaciones.

      Devuelve SOLO JSON válido.
    """

    try:
        # Codificar imagen/pdf para Gemini
        b64_data = base64.b64encode(file_bytes).decode('utf-8')
        
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[
                types.Content(
                    parts=[
                        types.Part.from_bytes(data=file_bytes, mime_type=mime_type),
                        types.Part.from_text(text=prompt)
                    ]
                )
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "invoiceNumber": types.Schema(type=types.Type.STRING),
                        "date": types.Schema(type=types.Type.STRING),
                        "dueDate": types.Schema(type=types.Type.STRING),
                        "supplierName": types.Schema(type=types.Type.STRING),
                        "supplierAddress": types.Schema(type=types.Type.STRING),
                        "clientName": types.Schema(type=types.Type.STRING),
                        "clientCif": types.Schema(type=types.Type.STRING),
                        "clientAddress": types.Schema(type=types.Type.STRING),
                        "items": types.Schema(
                            type=types.Type.ARRAY,
                            items=types.Schema(
                                type=types.Type.OBJECT,
                                properties={
                                    "description": types.Schema(type=types.Type.STRING),
                                    "quantity": types.Schema(type=types.Type.NUMBER),
                                    "unitPrice": types.Schema(type=types.Type.NUMBER),
                                    "total": types.Schema(type=types.Type.NUMBER),
                                }
                            )
                        ),
                        "subtotal": types.Schema(type=types.Type.NUMBER),
                        "taxRate": types.Schema(type=types.Type.NUMBER),
                        "taxAmount": types.Schema(type=types.Type.NUMBER),
                        "total": types.Schema(type=types.Type.NUMBER),
                        "notes": types.Schema(type=types.Type.STRING),
                    }
                )
            )
        )
        
        data = json.loads(response.text)
        data['filename'] = filename # Guardar referencia al archivo original
        return data

    except Exception as e:
        st.error(f"Error procesando {filename}: {str(e)}")
        return None

def generate_pdf_bytes(invoice_data, settings):
    pdf = FPDF()
    pdf.add_page()
    
    # Colores
    primary_r, primary_g, primary_b = 37, 99, 235 # Blue-600
    
    # 1. Header & Logo
    header_y = 20
    
    # Logo
    if settings.get('logo_path') and os.path.exists(settings['logo_path']):
        try:
            pdf.image(settings['logo_path'], x=10, y=10, w=30)
            header_y = 45
        except:
            pass

    # Proveedor (Arriba Izquierda o debajo de logo)
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(40, 40, 40)
    pdf.set_xy(10 if not settings.get('logo_path') else 45, 15 if settings.get('logo_path') else 15)
    
    supplier_name = invoice_data.get('supplierName') or "PROVEEDOR"
    pdf.cell(0, 10, supplier_name, new_x="LMARGIN", new_y="NEXT")
    
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(100, 100, 100)
    # Ajustar posición para dirección
    pdf.set_xy(10 if not settings.get('logo_path') else 45, 22 if settings.get('logo_path') else 22)
    pdf.multi_cell(80, 5, invoice_data.get('supplierAddress') or "")

    # Título FACTURA (Arriba Derecha)
    pdf.set_xy(150, 15)
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(primary_r, primary_g, primary_b)
    pdf.cell(50, 10, "FACTURA", align='R')
    
    # Metadatos (Debajo de título)
    pdf.set_xy(140, 25)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(30, 5, "Nº Factura:", align='R')
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(30, 5, str(invoice_data.get('invoiceNumber', '---')), align='R', new_x="LMARGIN", new_y="NEXT")
    
    pdf.set_xy(140, 30)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(30, 5, "Fecha:", align='R')
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(30, 5, str(invoice_data.get('date', '')), align='R')

    # 2. Cliente
    start_y_client = max(pdf.get_y(), header_y) + 15
    
    pdf.set_xy(10, start_y_client)
    pdf.set_fill_color(241, 245, 249)
    pdf.rect(10, start_y_client, 190, 8, 'F')
    
    pdf.set_xy(12, start_y_client + 1.5)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(primary_r, primary_g, primary_b)
    pdf.cell(0, 5, "FACTURAR A:")
    
    pdf.set_xy(10, start_y_client + 12)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 5, invoice_data.get('clientName') or "CLIENTE", new_x="LMARGIN", new_y="NEXT")
    
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(100, 100, 100)
    if invoice_data.get('clientCif'):
        pdf.cell(0, 5, f"CIF/NIF: {invoice_data.get('clientCif')}", new_x="LMARGIN", new_y="NEXT")
    pdf.multi_cell(0, 5, invoice_data.get('clientAddress') or "")

    # 3. Tabla
    pdf.set_y(pdf.get_y() + 10)
    
    # Cabecera Tabla
    pdf.set_fill_color(primary_r, primary_g, primary_b)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(95, 8, "Descripción", fill=True)
    pdf.cell(20, 8, "Cant.", align='R', fill=True)
    pdf.cell(35, 8, "Precio U.", align='R', fill=True)
    pdf.cell(40, 8, "Total", align='R', fill=True, new_x="LMARGIN", new_y="NEXT")
    
    # Items
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "", 9)
    fill = False
    for item in invoice_data.get('items', []):
        pdf.cell(95, 8, str(item.get('description', '')), border='B')
        pdf.cell(20, 8, str(item.get('quantity', 0)), align='R', border='B')
        pdf.cell(35, 8, f"{item.get('unitPrice', 0):.2f} €", align='R', border='B')
        pdf.cell(40, 8, f"{item.get('total', 0):.2f} €", align='R', border='B', new_x="LMARGIN", new_y="NEXT")

    # 4. Totales
    pdf.set_y(pdf.get_y() + 5)
    x_totals = 130
    
    pdf.set_x(x_totals)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(30, 6, "Subtotal:", align='R')
    pdf.set_text_color(0, 0, 0)
    pdf.cell(30, 6, f"{invoice_data.get('subtotal', 0):.2f} €", align='R', new_x="LMARGIN", new_y="NEXT")
    
    pdf.set_x(x_totals)
    pdf.set_text_color(100, 100, 100)
    tax_rate = invoice_data.get('taxRate', 21)
    pdf.cell(30, 6, f"IVA ({tax_rate}%):", align='R')
    pdf.set_text_color(0, 0, 0)
    pdf.cell(30, 6, f"{invoice_data.get('taxAmount', 0):.2f} €", align='R', new_x="LMARGIN", new_y="NEXT")
    
    pdf.set_x(x_totals)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(primary_r, primary_g, primary_b)
    pdf.cell(30, 10, "TOTAL:", align='R')
    pdf.cell(30, 10, f"{invoice_data.get('total', 0):.2f} €", align='R')

    # 5. Notas
    if invoice_data.get('notes'):
        pdf.set_y(pdf.get_y() + 15)
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_text_color(150, 150, 150)
        pdf.cell(0, 5, "NOTAS:", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 8)
        pdf.multi_cell(0, 5, invoice_data.get('notes'))

    return bytes(pdf.output())

# --- 3. UI: SIDEBAR CONFIGURACIÓN ---

with st.sidebar:
    st.title("⚙️ Configuración")
    
    with st.expander("Datos de Mi Empresa", expanded=not st.session_state.settings['name']):
        # Logo uploader
        uploaded_logo = st.file_uploader("Logo Empresa", type=['png', 'jpg', 'jpeg'])
        if uploaded_logo:
            # Save logo locally
            logo_path = os.path.join(FILES_DIR, "company_logo.png")
            with open(logo_path, "wb") as f:
                f.write(uploaded_logo.getbuffer())
            st.session_state.settings['logo_path'] = logo_path
            st.success("Logo actualizado")

        if st.session_state.settings['logo_path']:
            st.image(st.session_state.settings['logo_path'], width=100)

        # Form fields
        new_name = st.text_input("Razón Social", value=st.session_state.settings['name'])
        new_cif = st.text_input("CIF / NIF", value=st.session_state.settings['cif'])
        new_address = st.text_area("Dirección Fiscal", value=st.session_state.settings['address'])
        new_tax = st.number_input("IVA por defecto (%)", value=st.session_state.settings['defaultTaxRate'])
        
        if st.button("Guardar Configuración"):
            st.session_state.settings.update({
                "name": new_name,
                "cif": new_cif,
                "address": new_address,
                "defaultTaxRate": new_tax
            })
            save_json(SETTINGS_FILE, st.session_state.settings)
            st.success("Datos guardados correctamente.")

    st.divider()
    st.markdown("### 🗂️ Base de Datos Clientes")
    st.caption(f"{len(st.session_state.clients)} clientes guardados")
    # Podríamos añadir un gestor de clientes aquí si fuera necesario

# --- 4. UI: ÁREA PRINCIPAL ---

st.title("🧾 AlbaFactura AI")
st.markdown("Convierte tus **Albaranes** (PDF, Imagen) en **Facturas** automáticamente usando Inteligencia Artificial.")

if not st.session_state.settings['name']:
    st.warning("☝️ Configura primero los datos de tu empresa en el menú lateral.")

# TABS NAVIGATION
tab_upload, tab_editor, tab_export = st.tabs(["1. Subir Albaranes", "2. Revisar & Editar", "3. Exportar"])

# --- TAB 1: UPLOAD & PROCESS ---
with tab_upload:
    uploaded_files = st.file_uploader(
        "Arrastra tus albaranes aquí (Máx 10)", 
        type=['png', 'jpg', 'jpeg', 'pdf'], 
        accept_multiple_files=True
    )

    if uploaded_files:
        if st.button(f"Procesar {len(uploaded_files)} Archivos", type="primary"):
            st.session_state.processed_invoices = [] # Reset
            
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            for i, file in enumerate(uploaded_files):
                status_text.text(f"Procesando {file.name} con Gemini AI...")
                
                # Leer bytes
                bytes_data = file.getvalue()
                mime_type = file.type
                
                # LLAMADA A GEMINI
                data = process_invoice_with_gemini(bytes_data, mime_type, file.name)
                
                if data:
                    # 1. Aplicar Configuración Empresa (Proveedor)
                    if st.session_state.settings['name']:
                        data['supplierName'] = st.session_state.settings['name']
                        data['supplierAddress'] = f"{st.session_state.settings['address']}\nCIF: {st.session_state.settings['cif']}"
                        data['taxRate'] = st.session_state.settings['defaultTaxRate']
                        
                        # Recalcular totales con el nuevo IVA
                        subtotal = sum(item['total'] for item in data['items'])
                        tax_amount = round(subtotal * (data['taxRate'] / 100), 2)
                        data['subtotal'] = subtotal
                        data['taxAmount'] = tax_amount
                        data['total'] = subtotal + tax_amount

                    # 2. Buscar Cliente en BD (Autocompletado simple)
                    if data.get('clientName'):
                        client_match = next((c for c in st.session_state.clients if c['name'].lower() in data['clientName'].lower() or data['clientName'].lower() in c['name'].lower()), None)
                        if client_match:
                            data['clientName'] = client_match['name']
                            data['clientCif'] = client_match['cif']
                            data['clientAddress'] = client_match['address']
                    
                    st.session_state.processed_invoices.append(data)
                
                progress_bar.progress((i + 1) / len(uploaded_files))
            
            status_text.success("¡Procesamiento completado!")
            st.session_state.current_invoice_index = 0
            st.rerun() # Recargar para ir a la siguiente pestaña o actualizar estado

# --- TAB 2: EDITOR ---
with tab_editor:
    if not st.session_state.processed_invoices:
        st.info("No hay facturas procesadas. Sube archivos en la pestaña 1.")
    else:
        # Navegación entre facturas del lote
        col_nav_1, col_nav_2, col_nav_3 = st.columns([1, 4, 1])
        with col_nav_1:
            if st.button("⬅️ Anterior") and st.session_state.current_invoice_index > 0:
                st.session_state.current_invoice_index -= 1
                st.rerun()
        with col_nav_3:
            if st.button("Siguiente ➡️") and st.session_state.current_invoice_index < len(st.session_state.processed_invoices) - 1:
                st.session_state.current_invoice_index += 1
                st.rerun()
        
        with col_nav_2:
            st.markdown(f"<h3 style='text-align: center'>Factura {st.session_state.current_invoice_index + 1} de {len(st.session_state.processed_invoices)}</h3>", unsafe_allow_html=True)
            st.caption(f"Archivo original: {st.session_state.processed_invoices[st.session_state.current_invoice_index].get('filename')}")

        # EDITOR FORM
        current_inv = st.session_state.processed_invoices[st.session_state.current_invoice_index]
        
        # Guardar cambios automáticamente al modificar inputs
        def update_field(key, new_value):
            st.session_state.processed_invoices[st.session_state.current_invoice_index][key] = new_value

        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Cabecera")
            new_num = st.text_input("Nº Factura", current_inv.get('invoiceNumber', ''), key="inv_num")
            current_inv['invoiceNumber'] = new_num
            
            new_date = st.text_input("Fecha", current_inv.get('date', ''), key="inv_date")
            current_inv['date'] = new_date

        with c2:
            st.subheader("Cliente")
            
            # Autocompletado de clientes
            client_names = [c['name'] for c in st.session_state.clients]
            selected_client = st.selectbox(
                "Seleccionar Cliente (Existente)", 
                options=[""] + client_names, 
                index=0, 
                key="client_select"
            )
            
            # Si selecciona uno, rellenar datos
            if selected_client and selected_client != "":
                client_obj = next(c for c in st.session_state.clients if c['name'] == selected_client)
                current_inv['clientName'] = client_obj['name']
                current_inv['clientCif'] = client_obj['cif']
                current_inv['clientAddress'] = client_obj['address']
            
            # Campos editables
            c_name = st.text_input("Nombre Cliente", current_inv.get('clientName', ''))
            current_inv['clientName'] = c_name
            
            c_cif = st.text_input("CIF Cliente", current_inv.get('clientCif', ''))
            current_inv['clientCif'] = c_cif
            
            c_addr = st.text_area("Dirección Cliente", current_inv.get('clientAddress', ''))
            current_inv['clientAddress'] = c_addr
            
            # Botón guardar cliente
            if st.button("💾 Guardar Cliente en BD"):
                new_client = {"name": c_name, "cif": c_cif, "address": c_addr}
                # Actualizar o añadir
                st.session_state.clients = [c for c in st.session_state.clients if c['name'] != c_name]
                st.session_state.clients.append(new_client)
                save_json(CLIENTS_FILE, st.session_state.clients)
                st.success(f"Cliente {c_name} guardado.")

        st.divider()
        st.subheader("Conceptos (Líneas)")
        
        # Tabla editable (Data Editor de Streamlit es perfecto para esto)
        items_data = current_inv.get('items', [])
        
        # Configurar columnas para st.data_editor
        edited_items = st.data_editor(
            items_data,
            num_rows="dynamic",
            column_config={
                "description": "Descripción",
                "quantity": st.column_config.NumberColumn("Cant.", min_value=0, format="%.2f"),
                "unitPrice": st.column_config.NumberColumn("Precio U.", min_value=0, format="%.2f €"),
                "total": st.column_config.NumberColumn("Total", disabled=True, format="%.2f €")
            },
            use_container_width=True,
            key="editor_table"
        )
        
        # Recalcular totales basado en la edición
        new_subtotal = 0
        for item in edited_items:
            item['total'] = item['quantity'] * item['unitPrice']
            new_subtotal += item['total']
            
        current_inv['items'] = edited_items
        current_inv['subtotal'] = new_subtotal
        
        # Totales Finales
        col_t1, col_t2 = st.columns([3, 1])
        with col_t2:
            st.markdown("### Totales")
            st.metric("Subtotal", f"{current_inv['subtotal']:.2f} €")
            
            new_tax_rate = st.number_input("% IVA", value=float(current_inv.get('taxRate', 21)))
            current_inv['taxRate'] = new_tax_rate
            
            current_inv['taxAmount'] = current_inv['subtotal'] * (new_tax_rate / 100)
            current_inv['total'] = current_inv['subtotal'] + current_inv['taxAmount']
            
            st.metric("IVA", f"{current_inv['taxAmount']:.2f} €")
            st.metric("TOTAL", f"{current_inv['total']:.2f} €", delta_color="normal")

# --- TAB 3: EXPORTAR ---
with tab_export:
    if not st.session_state.processed_invoices:
        st.warning("No hay datos para exportar.")
    else:
        st.success(f"¡Listo para generar {len(st.session_state.processed_invoices)} facturas!")
        
        # Opción 1: Descargar PDF Individual (de la actual seleccionada en Editor)
        st.subheader("Vista Previa y Descarga Individual")
        current_inv_export = st.session_state.processed_invoices[st.session_state.current_invoice_index]
        
        pdf_bytes = generate_pdf_bytes(current_inv_export, st.session_state.settings)
        
        # Mostrar PDF (truco para mostrar PDF embebido en Streamlit)
        base64_pdf = base64.b64encode(pdf_bytes).decode('utf-8')
        pdf_display = f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="500" type="application/pdf"></iframe>'
        st.markdown(pdf_display, unsafe_allow_html=True)
        
        st.download_button(
            label="⬇️ Descargar este PDF",
            data=pdf_bytes,
            file_name=f"Factura_{current_inv_export.get('invoiceNumber')}.pdf",
            mime="application/pdf"
        )
        
        st.divider()
        
        # Opción 2: Descargar ZIP Lote Completo
        st.subheader("Descarga por Lotes")
        if st.button("📦 Generar ZIP con Todas las Facturas"):
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w") as zf:
                for inv in st.session_state.processed_invoices:
                    pdf_data = generate_pdf_bytes(inv, st.session_state.settings)
                    filename = f"Factura_{inv.get('invoiceNumber', 'borrador')}.pdf"
                    zf.writestr(filename, pdf_data)
            
            st.download_button(
                label="⬇️ Descargar ZIP Completo",
                data=zip_buffer.getvalue(),
                file_name=f"Facturas_Lote_{datetime.now().strftime('%Y%m%d')}.zip",
                mime="application/zip",
                type="primary"
            )

# Footer
st.markdown("---")
st.caption("AlbaFactura AI © 2024 - Desarrollado con Streamlit & Gemini 2.5")
