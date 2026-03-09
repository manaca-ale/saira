"""
set_crop.py — Ferramenta interativa de seleção de crop para câmeras SAIRA.

Uso:
    python set_crop.py --device esp32_001 --server http://localhost:5002
    python set_crop.py --device esp32_001 --image caminho/para/imagem.jpg
    python set_crop.py --device esp32_001 --server http://... --apply

Fluxo:
    1. Baixa a última imagem do device no servidor (ou usa --image local).
    2. Abre janela interativa: arraste para selecionar a região de interesse.
    3. Exibe os parâmetros calculados (crop_x, crop_y, crop_w, crop_h).
    4. Com --apply (ou confirmando no prompt), faz POST no servidor.

Dependências:
    pip install Pillow requests
"""

import argparse
import sys
import os
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk
import requests


# ── helpers ──────────────────────────────────────────────────────────────────

def fetch_latest_image(server: str, device_id: str) -> Image.Image:
    """Baixa o snapshot mais recente do esp32-server."""
    # Tenta endpoint de preview/latest; caso contrário usa /status para
    # descobrir o device e monta URL direta de arquivo.
    # O esp32-server serve as imagens em /uploads/<device>/<arquivo>.
    url = f"{server}/device/{device_id}/latest.jpg"
    r = requests.get(url, timeout=10)
    if r.status_code == 200:
        from io import BytesIO
        return Image.open(BytesIO(r.content))

    # Fallback: lista arquivos no dashboard JSON e pega o mais recente
    r2 = requests.get(f"{server}/dashboard/data", timeout=10)
    if r2.status_code == 200:
        data = r2.json()
        for dev in data.get("devices", []):
            if dev.get("device_id") == device_id:
                images = dev.get("recent_images", [])
                if images:
                    img_url = images[0].get("url", "")
                    if img_url:
                        r3 = requests.get(
                            img_url if img_url.startswith("http") else server + img_url,
                            timeout=10,
                        )
                        if r3.status_code == 200:
                            from io import BytesIO
                            return Image.open(BytesIO(r3.content))

    raise RuntimeError(
        f"Não foi possível baixar imagem do device '{device_id}' em {server}.\n"
        "Use --image para fornecer um arquivo local."
    )


def post_crop(server: str, device_id: str, crop: dict, token: str | None):
    url = f"{server}/device/{device_id}/config"
    headers = {}
    if token:
        headers["X-Admin-Token"] = token
    r = requests.post(url, json=crop, headers=headers, timeout=10)
    r.raise_for_status()
    return r


# ── GUI ───────────────────────────────────────────────────────────────────────

class CropSelector:
    MAX_W = 1200
    MAX_H = 800

    def __init__(self, root: tk.Tk, image: Image.Image):
        self.root = root
        self.orig_image = image
        self.orig_w, self.orig_h = image.size

        # Escala para caber na tela
        scale_x = self.MAX_W / self.orig_w
        scale_y = self.MAX_H / self.orig_h
        self.scale = min(scale_x, scale_y, 1.0)
        disp_w = int(self.orig_w * self.scale)
        disp_h = int(self.orig_h * self.scale)

        self.disp_image = image.resize((disp_w, disp_h), Image.LANCZOS)
        self.tk_image = ImageTk.PhotoImage(self.disp_image)

        self.root.title("SAIRA – Seleção de Crop")
        self.root.resizable(False, False)

        # Canvas
        self.canvas = tk.Canvas(root, width=disp_w, height=disp_h, cursor="crosshair")
        self.canvas.pack()
        self.canvas.create_image(0, 0, anchor="nw", image=self.tk_image)

        # Barra de info
        info_frame = ttk.Frame(root, padding=6)
        info_frame.pack(fill="x")

        self.lbl_orig = ttk.Label(
            info_frame,
            text=f"Resolução original: {self.orig_w}×{self.orig_h}px"
            + (f"  (exibindo em {disp_w}×{disp_h}, escala {self.scale:.2f})" if self.scale < 1 else ""),
        )
        self.lbl_orig.pack(anchor="w")

        self.lbl_crop = ttk.Label(info_frame, text="Arraste para selecionar a região de interesse.",
                                  foreground="gray")
        self.lbl_crop.pack(anchor="w")

        self.lbl_cmd = ttk.Label(info_frame, text="", foreground="blue", font=("Courier", 10))
        self.lbl_cmd.pack(anchor="w")

        btn_frame = ttk.Frame(root, padding=(6, 0, 6, 6))
        btn_frame.pack(fill="x")
        self.btn_apply = ttk.Button(btn_frame, text="✔ Aplicar no servidor",
                                    command=self._on_apply, state="disabled")
        self.btn_apply.pack(side="left", padx=(0, 6))
        ttk.Button(btn_frame, text="✖ Limpar crop (sem corte)",
                   command=self._on_clear).pack(side="left", padx=(0, 6))
        ttk.Button(btn_frame, text="Fechar", command=root.destroy).pack(side="right")

        # Estado do drag
        self._x0 = self._y0 = 0
        self._rect_id = None
        self.crop = None          # dict com crop_x/y/w/h em pixels originais
        self.apply_requested = False
        self.clear_requested = False

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)

    # ── drag handlers ─────────────────────────────────────────────────────────

    def _on_press(self, evt):
        self._x0, self._y0 = evt.x, evt.y
        if self._rect_id:
            self.canvas.delete(self._rect_id)
            self._rect_id = None

    def _on_drag(self, evt):
        if self._rect_id:
            self.canvas.delete(self._rect_id)
        self._rect_id = self.canvas.create_rectangle(
            self._x0, self._y0, evt.x, evt.y,
            outline="#00ff00", width=2, dash=(4, 4)
        )

    def _on_release(self, evt):
        x1, y1 = min(self._x0, evt.x), min(self._y0, evt.y)
        x2, y2 = max(self._x0, evt.x), max(self._y0, evt.y)
        if x2 - x1 < 4 or y2 - y1 < 4:
            return

        # Converte para coordenadas originais
        cx = int(x1 / self.scale)
        cy = int(y1 / self.scale)
        cw = int((x2 - x1) / self.scale)
        ch = int((y2 - y1) / self.scale)

        # Clip
        cx = max(0, min(cx, self.orig_w - 1))
        cy = max(0, min(cy, self.orig_h - 1))
        cw = min(cw, self.orig_w - cx)
        ch = min(ch, self.orig_h - cy)

        self.crop = {"crop_x": cx, "crop_y": cy, "crop_w": cw, "crop_h": ch}
        reduction = 100 * (1 - (cw * ch) / (self.orig_w * self.orig_h))

        self.lbl_crop.config(
            text=f"Crop: x={cx} y={cy} w={cw} h={ch}  "
                 f"({cw}×{ch}px, redução de área: {reduction:.1f}%)",
            foreground="green",
        )
        self.lbl_cmd.config(
            text=f"crop_x={cx}  crop_y={cy}  crop_w={cw}  crop_h={ch}"
        )
        self.btn_apply.config(state="normal")

    # ── buttons ───────────────────────────────────────────────────────────────

    def _on_apply(self):
        self.apply_requested = True
        self.root.destroy()

    def _on_clear(self):
        self.crop = {"crop_x": 0, "crop_y": 0, "crop_w": 0, "crop_h": 0}
        self.clear_requested = True
        self.apply_requested = True
        self.root.destroy()


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Seletor interativo de crop para câmeras SAIRA")
    parser.add_argument("--device", required=True, help="ID do device (ex: esp32_001)")
    parser.add_argument("--server", default="http://localhost:5002",
                        help="URL base do esp32-server (default: http://localhost:5002)")
    parser.add_argument("--image", help="Imagem local (jpg/png) em vez de baixar do servidor")
    parser.add_argument("--apply", action="store_true",
                        help="Aplica automaticamente após seleção (sem prompt)")
    parser.add_argument("--token", default=os.environ.get("SAIRA_ADMIN_TOKEN", ""),
                        help="X-Admin-Token para o endpoint /device/<id>/config")
    args = parser.parse_args()

    # 1. Carrega imagem
    if args.image:
        try:
            image = Image.open(args.image)
        except Exception as e:
            print(f"Erro ao abrir imagem: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        print(f"Baixando imagem de {args.server} para device '{args.device}'...")
        try:
            image = fetch_latest_image(args.server, args.device)
        except Exception as e:
            print(f"Erro: {e}", file=sys.stderr)
            sys.exit(1)

    print(f"Imagem carregada: {image.size[0]}×{image.size[1]}px")

    # 2. GUI de seleção
    root = tk.Tk()
    selector = CropSelector(root, image)
    root.mainloop()

    if selector.crop is None:
        print("Nenhuma região selecionada. Saindo sem alterações.")
        sys.exit(0)

    crop = selector.crop
    print(f"\nCrop selecionado:")
    print(f"  crop_x={crop['crop_x']}")
    print(f"  crop_y={crop['crop_y']}")
    print(f"  crop_w={crop['crop_w']}")
    print(f"  crop_h={crop['crop_h']}")

    if selector.clear_requested:
        print("(Limpando crop — device vai enviar imagem completa)")

    # 3. Aplica no servidor
    do_apply = args.apply or selector.apply_requested
    if not do_apply:
        resp = input("\nAplicar no servidor? [s/N] ").strip().lower()
        do_apply = resp in ("s", "sim", "y", "yes")

    if do_apply:
        print(f"\nEnviando para {args.server}/device/{args.device}/config ...")
        try:
            r = post_crop(args.server, args.device, crop, args.token or None)
            print(f"OK ({r.status_code}): {r.text[:200]}")
            print("\nO device vai buscar a nova config na próxima janela de polling (~30s).")
        except Exception as e:
            print(f"Erro ao enviar: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        print("Não aplicado. Para aplicar manualmente:")
        print(f"  POST {args.server}/device/{args.device}/config")
        print(f"  Body JSON: {crop}")


if __name__ == "__main__":
    main()
