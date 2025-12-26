import streamlit as st
import fitz  # PyMuPDF
import re
import io  # メモリ上でファイルを扱うために必要

# バージョン情報
VERSION = "Ver14.18 (Web)"


# --- ロジック部分（既存コードの関数） ---

def extract_panels_with_pos(page):
    panels = []
    page_text_dict = page.get_text("dict")

    # 厳格な正規表現（数字3-4桁 + 記号）
    pattern = re.compile(r'(\d{3,4})[ΛV∧∨A-Z\u039B\u2227\u2228]')

    w_pdf, h_pdf = page.rect.width, page.rect.height
    mid_x = w_pdf / 2

    GRID_START = 75
    footer_h = 25
    row_h = (h_pdf - GRID_START - footer_h) / 4

    for block in page_text_dict["blocks"]:
        if "lines" not in block: continue
        for line in block["lines"]:
            for span in line["spans"]:
                text = span["text"].replace(' ', '')
                match = pattern.search(text)

                if match:
                    num = int(match.group(1))
                    x0, y0, x1, y1 = span['bbox']
                    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2

                    col = 0 if cx < mid_x else 1
                    if cy < GRID_START:
                        row = 0
                    else:
                        raw_row = (cy - GRID_START) // row_h
                        row = int(min(max(raw_row, 0), 3))

                    area_id = col * 4 + row
                    panels.append({
                        "num": num,
                        "pack_id": num // 100,
                        "center": (cx, cy),
                        "page_num": page.number,
                        "area_id": area_id,
                        "col": col,
                        "row": row
                    })
    return panels


def process_pdf_in_memory(file_bytes):
    """
    バイト列(PDFデータ)を受け取り、処理後のPDFデータをバイト列で返す関数
    """
    # バイトストリームからPDFを開く
    doc = fitz.open(stream=file_bytes, filetype="pdf")

    full_sequence = []

    # データの解析
    for p_num in range(len(doc)):
        p_list = extract_panels_with_pos(doc[p_num])
        for a_id in range(8):
            a_panels = [p for p in p_list if p["area_id"] == a_id]
            if a_panels:
                ps = sorted(list({p["pack_id"] for p in a_panels}))
                full_sequence.append({
                    "p": p_num, "aid": a_id, "row": a_id % 4, "col": a_id // 4,
                    "min_p": min(ps), "p_set": ps, "panels": a_panels
                })

    h_line_flags = {}
    OFFSET_MAP = {0: 7, 1: -23, 2: 1, 3: -31}

    # 1. 水平境界線の描画
    for i, curr in enumerate(full_sequence):
        page = doc[curr["p"]]
        w, h = page.rect.width, page.rect.height
        v_line_x = (w / 2) + 4
        row_h = (h - 75 - 25) / 4
        p_num = curr["p"]
        aid = curr["aid"]

        def gmp(target_p, target_aid):
            d = next((x for x in full_sequence if x["p"] == target_p and x["aid"] == target_aid), None)
            return d["min_p"] if d else None

        should_draw_h = False
        prev_pack = full_sequence[i - 1]["min_p"] if i > 0 else None

        if p_num == 0 and aid == 0:
            should_draw_h = False
        elif aid == 4:
            mp0 = gmp(p_num, 0)
            if mp0 is not None:
                if curr["min_p"] != mp0: should_draw_h = True
            else:
                if curr["min_p"] != prev_pack: should_draw_h = True

            # 左右連動ルール
            if h_line_flags.get((p_num, 0)):
                should_draw_h = True
        else:
            if curr["min_p"] != prev_pack:
                should_draw_h = True

        if should_draw_h:
            y = 75 + (row_h * curr["row"]) + OFFSET_MAP.get(curr["row"], 0)
            xs, xe = (10, v_line_x) if curr["col"] == 0 else (v_line_x, w - 10)
            page.draw_line((xs, y), (xe, y), color=(1, 0, 0), width=6, stroke_opacity=0.4)
            h_line_flags[(p_num, aid)] = True

        if len(curr["p_set"]) > 1:
            for p in curr["panels"]:
                if p["pack_id"] != curr["min_p"]:
                    # 丸は太さ1.5 / 不透明度0.3
                    page.draw_circle(
                        p["center"],
                        25,
                        color=(1, 0, 0),
                        width=1.5,
                        stroke_opacity=0.3
                    )

    # 2. 縦境界線の描画
    for p_num in range(len(doc)):
        page = doc[p_num]
        w, h = page.rect.width, page.rect.height
        v_x = (w / 2) + 4
        row_h = (h - 75 - 25) / 4

        def gy(r):
            return 75 + (row_h * r) + OFFSET_MAP.get(r, 0)

        def gmp_v(aid):
            d = next((x for x in full_sequence if x["p"] == p_num and x["aid"] == aid), None)
            return d["min_p"] if d else None

        v_line_active = [False] * 4
        for r in range(4):
            aid_l, aid_r = r, r + 4
            mp_l, mp_r = gmp_v(aid_l), gmp_v(aid_r)

            if mp_l is not None and mp_r is not None and mp_l == mp_r:
                continue

            if h_line_flags.get((p_num, aid_l)) or h_line_flags.get((p_num, aid_r)):
                v_line_active[r] = True
            elif r > 0 and v_line_active[r - 1]:
                v_line_active[r] = True

            if r == 1 and h_line_flags.get((p_num, 4)) and h_line_flags.get((p_num, 2)) and not h_line_flags.get(
                    (p_num, 5)):
                v_line_active[r] = True

            # 斜め結合判定
            if r > 0 and v_line_active[r]:
                aid_ur = (r - 1) + 4
                mp_ur = gmp_v(aid_ur)
                if mp_l is not None and mp_r is None and mp_ur is not None:
                    if mp_l == mp_ur:
                        v_line_active[r] = False

        # 連番(差が1)なら縦線を消す
        if r == 0 and mp_l is not None and mp_r is not None:
            if v_line_active[0]:
                diff = abs(mp_l - mp_r)
                if diff == 1:
                    v_line_active[0] = False

        for r in range(4):
            if v_line_active[r]:
                if r < 3:
                    def has_next(a):
                        return next((x for x in full_sequence if x["p"] == p_num and x["aid"] == a), None) is not None

                    any_p_curr = has_next(r) or has_next(r + 4)
                    any_p_next = has_next(r + 1) or has_next(r + 5)
                    any_l_next = h_line_flags.get((p_num, r + 1)) or h_line_flags.get((p_num, r + 5))

                    if not any_p_curr and not any_p_next and not any_l_next:
                        page.draw_line((v_x, gy(r) - 3), (v_x, gy(r) + 3), color=(1, 0, 0), width=6, stroke_opacity=0.4)
                        break

                y_start = gy(r) - 3
                y_end = gy(r + 1) + 3 if r < 3 else h - 25
                page.draw_line((v_x, y_start), (v_x, y_end), color=(1, 0, 0), width=6, stroke_opacity=0.4)

    # 処理結果をメモリバッファに保存
    output_buffer = io.BytesIO()
    doc.save(output_buffer)
    doc.close()

    # バッファのポインタを先頭に戻して返す
    output_buffer.seek(0)
    return output_buffer


# --- Streamlit UI部分 ---

def main():
    st.set_page_config(page_title="床パネル自動描画ツール", layout="wide")

    st.title(f"📐 床パネル自動描画ツール {VERSION}")
    st.markdown("PDFファイルをアップロードすると、赤丸と境界線を描画してダウンロードできます。")

    # ファイルアップロード（複数可）
    uploaded_files = st.file_uploader(
        "処理するPDFファイルを選択してください",
        type="pdf",
        accept_multiple_files=True
    )

    if uploaded_files:
        st.write("---")
        st.write(f"📁 {len(uploaded_files)} 個のファイルが選択されました")

        for uploaded_file in uploaded_files:
            # 各ファイルを処理
            # Streamlitではファイル名が変わることがあるため、元のファイル名を使用
            original_filename = uploaded_file.name

            with st.spinner(f"処理中... {original_filename}"):
                try:
                    # アップロードされたファイルのバイトデータを読み込む
                    file_bytes = uploaded_file.read()

                    # 処理実行
                    processed_pdf_io = process_pdf_in_memory(file_bytes)

                    # ダウンロードボタンのファイル名作成
                    output_filename = f"床パネル書込済_{original_filename}"

                    # ダウンロードボタン表示
                    st.success(f"完了: {original_filename}")
                    st.download_button(
                        label=f"⬇️ {output_filename} をダウンロード",
                        data=processed_pdf_io,
                        file_name=output_filename,
                        mime="application/pdf"
                    )

                except Exception as e:
                    st.error(f"エラーが発生しました ({original_filename}): {e}")


if __name__ == "__main__":
    main()


