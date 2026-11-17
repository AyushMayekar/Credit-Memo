from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

from jinja2 import (
    Environment,
    FileSystemLoader,
    select_autoescape,
)
from playwright.sync_api import sync_playwright

from app.core.config import settings
from app.db.models import CreditMemo


class CreditMemoRenderingService:
    def __init__(self) -> None:
        template_directory = Path(__file__).resolve().parents[1] / "templates"

        environment = Environment(
            loader=FileSystemLoader(template_directory),
            autoescape=select_autoescape(["html", "xml"]),
            auto_reload=True,
            cache_size=0,
        )

        self.template = environment.get_template("credit_memo_template.html")

    def render_html(
        self,
        memo: CreditMemo,
    ) -> Path:
        output_directory = self._output_directory(memo)

        html_path = output_directory / (f"memo_v{memo.version_number}.html")

        rendered_html = self.template.render(
            memo=memo.memo_content,
        )

        temporary_path = output_directory / (f".memo_{uuid4().hex}.html.tmp")

        temporary_path.write_text(
            rendered_html,
            encoding="utf-8",
        )

        os.replace(
            temporary_path,
            html_path,
        )

        memo.generated_html_path = str(html_path)

        return html_path

    def render_pdf(
        self,
        memo: CreditMemo,
    ) -> Path:
        html_path = self.render_html(memo)
        output_directory = self._output_directory(memo)

        pdf_path = output_directory / (f"memo_v{memo.version_number}.pdf")

        temporary_pdf_path = output_directory / (f".memo_{uuid4().hex}.pdf.tmp")

        pdf_path.unlink(missing_ok=True)
        temporary_pdf_path.unlink(missing_ok=True)

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    channel="msedge",
                    headless=True,
                )

                page = browser.new_page()

                page.goto(
                    html_path.as_uri(),
                    wait_until="networkidle",
                )

                page.emulate_media(
                    media="print",
                )

                page.evaluate("""
                    async () => {
                        if (document.fonts?.ready) {
                            await document.fonts.ready;
                        }

                        await new Promise((resolve) => {
                            requestAnimationFrame(() => {
                                requestAnimationFrame(resolve);
                            });
                        });
                    }
                    """)

                page.pdf(
                    path=str(temporary_pdf_path),
                    format="A4",
                    print_background=True,
                    display_header_footer=False,
                    prefer_css_page_size=True,
                    margin={
                        "top": "18mm",
                        "right": "16mm",
                        "bottom": "18mm",
                        "left": "16mm",
                    },
                )

                browser.close()

            if (
                not temporary_pdf_path.exists()
                or temporary_pdf_path.stat().st_size == 0
            ):
                raise RuntimeError("Playwright did not produce a valid PDF.")

            os.replace(
                temporary_pdf_path,
                pdf_path,
            )

        except Exception as exc:
            temporary_pdf_path.unlink(missing_ok=True)

            raise RuntimeError(f"Credit memo PDF generation failed: {exc}") from exc

        memo.generated_pdf_path = str(pdf_path)

        return pdf_path

    def _output_directory(
        self,
        memo: CreditMemo,
    ) -> Path:
        output_directory = (
            settings.resolve_path(settings.generated_dir)
            / "credit_memos"
            / str(memo.application_id)
        )

        output_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        return output_directory
