import os
import requests
from PIL import Image
from datetime import datetime
import win32com.client
from urllib.parse import urlparse, parse_qs
import sys

def get_params():
    if len(sys.argv) > 1:
        url = sys.argv[1]
        parsed = urlparse(url)
        return parse_qs(parsed.query)
    return {}

def scan_multiple():
    wia = win32com.client.Dispatch("WIA.CommonDialog")
    device = wia.ShowSelectDevice()

    images = []

    while True:
        print("📄 Escaneando página...")

        item = device.Items[0]
        image = wia.ShowTransfer(item)

        filename = f"scan_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        image.SaveFile(filename)

        images.append(filename)

        continuar = input("➡️ Coloque próxima folha e pressione ENTER (ou digite 'n' para finalizar): ")

        if continuar.lower() == 'n':
            break

    return images

def convert_multiple_to_pdf(image_paths):
    if not image_paths:
        raise Exception("Nenhuma imagem foi escaneada.")

    images = []

    for path in image_paths:
        img = Image.open(path).convert('RGB')
        images.append(img)

    pdf_path = f"scan_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"

    images[0].save(
        pdf_path,
        save_all=True,
        append_images=images[1:]
    )

    print(f"📦 PDF criado com {len(images)} páginas")

    return pdf_path

def send_to_api(pdf_path, categoria, pasta):
    url = "http://localhost:8000/upload-scan"

    with open(pdf_path, 'rb') as f:
        data = {
            "categoria": categoria,
            "pasta": pasta
        }

        files = {'file': f}

        response = requests.post(url, files=files, data=data)

    print(response.json())

def get_base_path():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))


if __name__ == "__main__":
    print("🚀 Iniciando digitalização...")

    params = get_params()

    categoria = params.get("categoria", [""])[0]
    pasta = params.get("pasta", [""])[0]

    print("📁 Categoria:", categoria)
    print("📁 Pasta:", pasta)

    # 🔥 validação
    if not categoria or not pasta:
        print("❌ Categoria ou pasta não informada!")
        input("Pressione ENTER para sair...")
        sys.exit()

    BASE_DIR = get_base_path()
    pdf_path = os.path.join(BASE_DIR, "teste.pdf")

    if os.path.exists(pdf_path):
        print("🧪 Modo TESTE")
        print("📤 Enviando arquivo para o sistema...")
        send_to_api(pdf_path, categoria, pasta)
    else:
        print("📄 Modo SCANNER REAL")

        try:
            imgs = scan_multiple()
        except Exception as e:
            print("❌ Erro ao acessar scanner:", e)
            input("Pressione ENTER para sair...")
            sys.exit()

        pdf = convert_multiple_to_pdf(imgs)

        print("📤 Enviando arquivo para o sistema...")
        send_to_api(pdf, categoria, pasta)

        # 🔥 limpar imagens
        for img_path in imgs:
            os.remove(img_path)

    print("✅ Finalizado!")