from __future__ import annotations

import os

import gradio as gr

from service import build_ui_response, configured_limits


MAX_FILES, MAX_FILE_MB, MAX_TOTAL_MB = configured_limits()

CSS = """
.gradio-container { max-width: 1080px !important; direction: rtl; }
.markdown-body, textarea, .prose { direction: rtl; text-align: right; }
footer { display: none !important; }
"""

with gr.Blocks(
    title="MarkItDown — محول الملفات إلى Markdown", css=CSS
) as demo:
    gr.Markdown(
        """
# محول الملفات إلى Markdown

ارفع ملفاتك لتحويلها بواسطة **Microsoft MarkItDown** إلى Markdown مناسب للبحث،
قواعد المعرفة، وأنظمة الذكاء الاصطناعي. تبقى النتائج مؤقتة على خادم التشغيل فقط.
"""
    )

    with gr.Row():
        files = gr.File(
            label="الملفات",
            file_count="multiple",
            type="filepath",
        )
        with gr.Column():
            gr.Markdown(
                f"""
**حدود هذه النسخة**

- حتى **{MAX_FILES}** ملفًا في العملية.
- حتى **{MAX_FILE_MB} MB** لكل ملف.
- حتى **{MAX_TOTAL_MB} MB** إجمالًا.
- ملفات ZIP معطلة افتراضيًا لأسباب أمنية، ويمكن تفعيلها من إعدادات الخادم.
"""
            )
            convert_button = gr.Button("تحويل الملفات", variant="primary")
            gr.ClearButton([files], value="مسح الاختيار")

    status = gr.Markdown(label="حالة التحويل")
    preview = gr.Code(
        label="معاينة Markdown لأول ملف ناجح",
        language="markdown",
        lines=22,
    )
    download = gr.File(label="تنزيل النتيجة")

    convert_button.click(
        fn=build_ui_response,
        inputs=files,
        outputs=[preview, download, status],
        api_name="convert",
    )

if __name__ == "__main__":
    demo.queue(default_concurrency_limit=2, max_size=8).launch(
        server_name="0.0.0.0",
        server_port=int(os.getenv("PORT", "7860")),
        show_error=True,
    )
