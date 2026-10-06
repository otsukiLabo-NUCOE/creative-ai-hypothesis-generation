# make_rater_guide.py — 評価者送付用の「実施の手引き」を ../rater_package/ に生成する
# （依頼者用の実施マニュアルから、依頼者だけの作業・対応表ファイル・条件に関する記述を除いたもの。
#   盲検を保つため、生成条件の内容には一切触れない）
import os

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("GUIDE_OUT", os.path.join(HERE, "..", "rater_package", "盲検評価_実施の手引き（評価者用）.docx"))
JP = "游ゴシック"

doc = Document()
sec = doc.sections[0]
sec.page_height, sec.page_width = Cm(29.7), Cm(21.0)
for side in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
    setattr(sec, side, Cm(2.0))
for name in ("Normal", "List Bullet", "List Number", "Heading 1", "Heading 2", "Title"):
    s = doc.styles[name]
    s.font.name = "Times New Roman"
    rpr = s.element.get_or_add_rPr()
    rf = rpr.find(qn("w:rFonts"))
    if rf is None:
        rf = OxmlElement("w:rFonts"); rpr.append(rf)
    rf.set(qn("w:eastAsia"), JP)
    for a in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
        if rf.get(qn(a)) is not None:
            del rf.attrib[qn(a)]
doc.styles["Normal"].font.size = Pt(10.5)
doc.styles["Normal"].paragraph_format.space_after = Pt(4)
for name, size in (("Heading 1", 14), ("Heading 2", 11.5), ("Title", 18)):
    st = doc.styles[name]
    st.font.size = Pt(size); st.font.bold = True; st.font.color.rgb = RGBColor(0, 0, 0)


def p(text="", bold=None, size=None, align=None):
    para = doc.add_paragraph()
    if bold:
        para.add_run(bold).bold = True
    r = para.add_run(text)
    if size:
        r.font.size = Pt(size)
    if align:
        para.alignment = align
    return para


def bullet(text, bold=None, style="List Bullet"):
    para = doc.add_paragraph(style=style)
    if bold:
        para.add_run(bold).bold = True
    para.add_run(text)


def shade(cell, fill):
    tcPr = cell._tc.get_or_add_tcPr()
    sh = OxmlElement("w:shd"); sh.set(qn("w:val"), "clear"); sh.set(qn("w:color"), "auto"); sh.set(qn("w:fill"), fill)
    tcPr.append(sh)


def table(rows, widths):
    t = doc.add_table(rows=len(rows), cols=len(rows[0]))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, row in enumerate(rows):
        for j, val in enumerate(row):
            c = t.cell(i, j)
            c.width = Cm(widths[j]); c.text = ""
            r = c.paragraphs[0].add_run(val); r.font.size = Pt(9.5)
            if i == 0:
                r.bold = True; shade(c, "D9D9D9")
    doc.add_paragraph()


def box(lines, fill):
    t = doc.add_table(rows=1, cols=1); t.style = "Table Grid"
    c = t.cell(0, 0); c.width = Cm(17); shade(c, fill); c.text = ""
    for k, (b, txt) in enumerate(lines):
        para = c.paragraphs[0] if k == 0 else c.add_paragraph()
        if b:
            r = para.add_run(b); r.bold = True; r.font.size = Pt(10)
        r = para.add_run(txt); r.font.size = Pt(10)
    doc.add_paragraph()


# ======================================================================== 表紙
doc.add_paragraph("盲検評価 実施の手引き", style="Title").alignment = WD_ALIGN_PARAGRAPH.CENTER
p("— 評価者の皆様へ：いつ・何をしていただくか —", size=12, align=WD_ALIGN_PARAGRAPH.CENTER)
p("依頼者：大槻 明（日本大学 経済学部）　連絡先：otsuki.akira@nihon-u.ac.jp", size=9.5,
  align=WD_ALIGN_PARAGRAPH.CENTER)

box([("この度はご協力いただき、誠にありがとうございます。", ""),
     ("", "この手引きでは、評価作業の流れ（いつ・何をするか）を説明します。"
          "採点基準の詳細は、同封の「評価者マニュアル」をご覧ください。")], "DDEBF7")

# ======================================================================== 1
doc.add_heading("1. お願いしたいこと", level=1)
table([
    ["項目", "内容"],
    ["作業の内容", "AIが自動生成した英語の研究原稿20本を読み、3つの観点（技術的妥当性・再現性・重要性）を1〜5点で採点して、評価シートに記入する"],
    ["所要時間", "1本あたり約12分、合計約4時間（練習を含む）。何日かに分けて構いません"],
    ["提出期限", "2026年10月　　日（　）"],
    ["提出物", "記入済みの評価シート（Excelファイル）1つ"],
    ["提出方法", "ファイル名を変えずに、依頼者（大槻）へメールで返送"],
], [3.5, 13.5])

# ======================================================================== 2
doc.add_heading("2. お送りしたファイル", level=1)
table([
    ["ファイル", "内容"],
    ["盲検評価_実施の手引き（評価者用）.docx", "この手引き"],
    ["評価者マニュアル_Rater_Manual.docx", "採点基準の詳細（最初に必ずお読みください）"],
    ["manuscripts\\P00_practice.docx", "練習用の原稿（1本）。分析には使いません"],
    ["manuscripts\\M0＊＊.docx（20ファイル）", "評価していただく原稿（20本）。番号はランダムで飛び飛びです。番号や順番に意味はありません"],
    ["評価シート_R＊.xlsx", "採点を記入するシート（あなた専用。読む順番が書かれています）"],
], [7.0, 10.0])

# ======================================================================== 3
doc.add_heading("3. 作業の流れ", level=1)
table([
    ["順番", "やること", "目安の時間"],
    ["1", "「評価者マニュアル」を通して読む（特に「4. 採点基準」）", "20分"],
    ["2", "練習用原稿 P00_practice.docx を読み、評価シートの「練習」シートに採点してみる（分析には使いません）", "20分"],
    ["3", "評価シートの「評価」シートに書かれた順番（position 1→20）で原稿を読み、1本読むごとにその行を記入する", "12分 × 20本"],
    ["", "記入項目：技術的妥当性・再現性・重要性（各1〜5点、プルダウンで選択）、コメント（任意）", ""],
    ["4", "「評価者情報」シートに、氏名・所属・専門分野、この研究に関わっていないことの確認、謝辞への氏名掲載の可否を記入する", "5分"],
    ["5", "評価シートを、ファイル名を変えずに依頼者へメールで返送する", "—"],
], [1.5, 12.5, 3.0])
p("進め方の例：1日目にマニュアルと練習、2日目以降に1日4〜5本ずつ。期限の2〜3日前までに半分以上終えておくと安心です。", size=9.5)

# ======================================================================== 4
doc.add_heading("4. 守っていただきたいこと", level=1)
box([("", "この評価は、どの原稿がどのように作られたかを評価者に伏せて行う「盲検評価」です。公平な評価のため、次の4点をお守りください。")],
    "FCE4D6")
for b, t in [("独立して評価する：", "他の評価者とは、評価が終わるまで原稿や点数について話さないでください。"),
             ("内容だけで評価する：", "原稿がどのように作られたかを推測して、点数を調整しないでください。"),
             ("生成AIを使わない：", "ChatGPT・Gemini・Claude などに原稿を読ませたり、要約・採点させたりしないでください。"),
             ("原稿を外部に出さない：", "原稿は未発表の研究資料です。第三者に渡したり、インターネットにアップロードしたりしないでください。評価終了後は削除していただいて構いません。")]:
    bullet(t, bold=b, style="List Number")

# ======================================================================== 5
doc.add_heading("5. 採点のポイント", level=1)
for t in ["実験結果や引用文献がないことでは減点しないでください（すべての原稿に共通の条件です）。実験は「今後の計画」として妥当かどうかで評価してください。",
          "英語のうまさ・長さ・見た目ではなく、内容で評価してください。",
          "原稿中に具体的な数値が書かれていても、実際の実験に基づくものではありません。それを根拠に高く評価しないでください。",
          "似たテーマの原稿があっても、1本ずつ独立に採点してください。",
          "迷ったときは、評価者マニュアルの点数ごとの説明に一番近い点数を選んでください。",
          "AIが専門でなくても問題ありません。技術的妥当性（数式・論理の整合性）と再現性（手法の記述の具体性）は、ご自身の専門の感覚で評価してください。アイデアの新しさ（独創性）は評価項目に含めていません（評価者マニュアル 4.4〜4.5）。"]:
    bullet(t)

# ======================================================================== 6
doc.add_heading("6. よくある質問", level=1)
for q, a in [
    ("どの原稿がどの条件で作られたのか教えてもらえますか。", "公平な評価のため、評価がすべて終わってからご説明します。"),
    ("専門外のテーマの原稿があります。", "分かる範囲で採点してください。"),
    ("数式がおかしい、または意味が通らない箇所があります。", "技術的妥当性の点数に反映し、必要ならコメント欄に一言書いてください。"),
    ("原稿の途中で文章が切れています。", "読める範囲で採点し、コメント欄に「途中で切れている」と書いてください。"),
    ("評価シートのプルダウンが動きません。", "Excel 上部の「編集を有効にする」を押してください。それでも動かない場合は、数字を直接入力していただいて構いません。"),
    ("期限に間に合いそうにありません。", "早めに依頼者へご連絡ください。終わった分だけでも返送いただけると助かります。"),
    ("採点基準について質問があります。", "依頼者へメールでお問い合わせください。公平のため、同じ回答を他の評価者にもお送りすることがあります。"),
]:
    p(a, bold=f"Q. {q}\nA. ")

# ======================================================================== 7
doc.add_heading("7. 提出前のチェックリスト", level=1)
for t in ["「評価」シートの20本すべてに、3観点の点数を記入した",
          "「評価者情報」シートを記入した",
          "ファイル名を変えていない",
          "評価が終わるまで、他の評価者と相談していない／生成AIを使っていない"]:
    para = doc.add_paragraph()
    para.add_run("☐  ").font.size = Pt(12)
    para.add_run(t)

p("")
p("ご不明な点は、いつでも依頼者（otsuki.akira@nihon-u.ac.jp）までご連絡ください。ご協力に心より感謝いたします。")

doc.save(OUT)
print("saved", OUT)
