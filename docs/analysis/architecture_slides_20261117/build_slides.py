from pathlib import Path
import subprocess
import fitz

P = Path(__file__).parent
names = ["01_사용자경험_서비스개념도", "02_전체시스템_아키텍처", "03_LangGraph_상담처리흐름도"]
merged = fitz.open()
for name in names:
    svg = P / (name + ".svg")
    subprocess.run(["inkscape", str(svg), "--export-type=png", f"--export-filename={P / (name + '.png')}", "--export-width=2560"], check=True)
    pdf = P / (name + ".pdf")
    subprocess.run(["inkscape", str(svg), "--export-type=pdf", f"--export-filename={pdf}"], check=True)
    doc = fitz.open(pdf)
    merged.insert_pdf(doc)
    doc.close()
merged.save(P / "AI_Legal_Helper_아키텍처_발표자료_3장.pdf", garbage=4, deflate=True)
print("완료: PNG 3장, PDF 3장, 통합 PDF")
