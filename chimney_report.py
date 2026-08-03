"""
chimney_report.py — Builds the Chimney Inspection defect report PDF.

Layout:
    Page 1  — cover page: report title, full chimney photo, chimney details
              (asset name / structure type / inspection type / scope).
    Page 2+ — one findings table per page (portrait A4):
                  Defect ID | Element | Type | Severity | Distance from Ground |
                  Location | Coordinates (Direction) | Area | Image
              7 defects per page.
"""
import os
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, PageBreak, KeepTogether
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT

DEFECTS_PER_PAGE = 8
# The first findings page also carries the report heading/title block, so
# it has less room — one fewer defect fits there. Every page after that
# has no heading at all (just the column header + defect rows), so it
# gets the full 8 and a taller row height to match, since there's more
# room to spread across.
DEFECTS_PER_PAGE_FIRST = 7
# Explicit row heights so defects actually fill a full page rather than
# auto-sizing to whatever their content needs (which could leave a mostly
# empty page, or crowd rows together — the same "settle within a full
# page" problem solved for tower_report.py's half-page blocks earlier).
# DEFECTS_HEADER_ROW_HEIGHT is set to the header's own measured natural
# height (35pt for its 2-line labels at this font size + padding) rather
# than a guessed round number — an underestimate here would make
# ReportLab silently expand the header row beyond what was budgeted for
# it, eating into the space counted on for the data rows and pushing the
# last one onto a new page. Both row heights include a real safety
# margin beyond the bare theoretical fit for the same reason — tested
# empirically (see chimney_report.py dev notes) rather than trusting the
# arithmetic alone, since a too-tight value overflows silently instead
# of raising an error.
DEFECTS_HEADER_ROW_HEIGHT = 35
DEFECTS_ROW_HEIGHT = 27.3 * mm             # first page — title block present
DEFECTS_ROW_HEIGHT_NO_HEADING = 30 * mm    # later pages — no title block, more room
PAGE_W, PAGE_H = A4  # portrait

DROGO_LOGO_REL_PATH = 'images/drogo_logo.png'
LOGO_HEADER_HEIGHT = 11 * mm  # logo's own height in the page header band
LOGO_HEADER_TOP_GAP = 8 * mm  # space between the very top of the page and the logo


def _draw_page_header(static_root, client_logo_path):
    """Returns an onPage callback for doc.build() — draws the Drogo
    Aerospace logo on the right and (if the project has one) the
    client's own logo on the left, on every single page including the
    cover. Drawn directly on the canvas rather than as a flowable, so it
    sits in the reserved top margin band without affecting the story's
    own content flow."""
    def _draw(canvas, doc):
        canvas.saveState()
        top_y = PAGE_H - LOGO_HEADER_TOP_GAP - LOGO_HEADER_HEIGHT

        drogo_path = os.path.join(static_root, DROGO_LOGO_REL_PATH)
        if os.path.exists(drogo_path):
            try:
                from PIL import Image as PILImage
                with PILImage.open(drogo_path) as pil_img:
                    iw, ih = pil_img.size
                w = LOGO_HEADER_HEIGHT * (iw / float(ih))
                canvas.drawImage(drogo_path, PAGE_W - 10 * mm - w, top_y, width=w, height=LOGO_HEADER_HEIGHT,
                                  preserveAspectRatio=True, mask='auto')
            except Exception:
                pass

        if client_logo_path:
            full_client_path = os.path.join(static_root, client_logo_path)
            if os.path.exists(full_client_path):
                try:
                    from PIL import Image as PILImage
                    with PILImage.open(full_client_path) as pil_img:
                        iw, ih = pil_img.size
                    w = LOGO_HEADER_HEIGHT * (iw / float(ih))
                    canvas.drawImage(full_client_path, 10 * mm, top_y, width=w, height=LOGO_HEADER_HEIGHT,
                                      preserveAspectRatio=True, mask='auto')
                except Exception:
                    pass

        canvas.restoreState()
    return _draw

# Available width inside the Image column's cell, for sizing defect
# photos to fully cover the cell (cropped to match its aspect ratio,
# touching the cell's borders on every side) — the Image column has its
# padding removed entirely (see the ('LEFTPADDING', (8, 1), ...) etc.
# overrides below) specifically so the photo can reach the cell edges.
# Column width is fixed regardless of page (26mm), but cell HEIGHT
# varies by which row height applies on a given page — see row_height
# passed into _defect_row for that half of the sizing.
IMAGE_CELL_AVAILABLE_W = 28.72 * mm


def _styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name='CellText', fontSize=7.5, leading=10, alignment=TA_CENTER))
    styles.add(ParagraphStyle(
        name='CellTextLeft', fontSize=8.5, leading=11, alignment=0))
    styles.add(ParagraphStyle(
        name='ReportTitle', fontSize=17, leading=21, spaceAfter=2, fontName='Helvetica-Bold'))
    styles.add(ParagraphStyle(
        name='ReportSubtitle', fontSize=10, leading=13, textColor=colors.HexColor('#555555')))
    styles.add(ParagraphStyle(
        name='CoverTitle', fontSize=22, leading=27, alignment=TA_CENTER,
        fontName='Helvetica-Bold', textColor=colors.HexColor('#1b1e24')))
    styles.add(ParagraphStyle(
        name='CoverSubtitle', fontSize=11.5, leading=15, alignment=TA_CENTER,
        textColor=colors.HexColor('#555555')))
    styles.add(ParagraphStyle(
        name='CoverSectionHead', fontSize=12.5, leading=16, fontName='Helvetica-Bold',
        textColor=colors.HexColor('#1b1e24'), spaceBefore=10, spaceAfter=6))
    styles.add(ParagraphStyle(
        name='CoverDetailLabel', fontSize=9.5, leading=13, fontName='Helvetica-Bold',
        textColor=colors.HexColor('#1b1e24')))
    styles.add(ParagraphStyle(
        name='CoverDetailValue', fontSize=9.5, leading=13, alignment=TA_LEFT,
        textColor=colors.HexColor('#333333')))
    return styles


# ── Cover page ────────────────────────────────────────────────────────────────

def _build_cover_page(project, defects, static_root, styles, cover_image_path):
    # Water Tank projects will get their own dedicated cover page later —
    # for now every project (regardless of asset_category) uses the
    # chimney cover page, same as before that field existed.
    story = []
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph('DIGITAL INSPECTION AND', styles['CoverTitle']))
    story.append(Paragraph('HEALTH ASSESSMENT REPORT', styles['CoverTitle']))
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph('DROGO AEROSPACE — Chimney / Stack Inspection', styles['CoverSubtitle']))
    story.append(Spacer(1, 8 * mm))

    # Full asset photo. A vertical/portrait chimney photo (the whole
    # structure base-to-top) is sized by HEIGHT first, using most of the
    # page — that's the point of a vertical shot, showing the complete
    # chimney, and capping it the same way a landscape image is capped
    # would just crop off the top or bottom. A landscape photo keeps the
    # original width-first sizing, since it doesn't have that same "show
    # the whole height" need.
    usable_w = PAGE_W - 20 * mm  # matches the doc's 10mm+10mm left/right margins
    max_portrait_h = 130 * mm  # dominant on the page, but leaves real room for the details table below
    max_landscape_h = 110 * mm
    img_added = False
    if cover_image_path and os.path.exists(cover_image_path):
        try:
            from PIL import Image as PILImage
            with PILImage.open(cover_image_path) as pil_img:
                pil_img.verify()
            with PILImage.open(cover_image_path) as pil_img:
                iw, ih = pil_img.size
            aspect = ih / float(iw) if iw else 0.6
            is_portrait = ih > iw

            if is_portrait:
                img_h = max_portrait_h
                img_w = img_h / aspect
                if img_w > usable_w:
                    img_w = usable_w
                    img_h = img_w * aspect
            else:
                img_w = usable_w
                img_h = img_w * aspect
                if img_h > max_landscape_h:
                    img_h = max_landscape_h
                    img_w = img_h / aspect

            story.append(Image(cover_image_path, width=img_w, height=img_h, hAlign='CENTER'))
            img_added = True
        except Exception:
            img_added = False

    if not img_added:
        placeholder = Table([[Paragraph('Chimney photo not available', styles['CellText'])]],
                             colWidths=[usable_w], rowHeights=[60 * mm])
        placeholder.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), 0.75, colors.HexColor('#c5cad4')),
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f4f6f9')),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        story.append(placeholder)

    story.append(Spacer(1, 10 * mm))

    scope = (project.inspection_scope or '').strip() or (
        'Complete visual assessment of the chimney/stack structure — shell, '
        'base and top rim — captured via drone-based 3D digital-twin inspection.'
    )

    detail_rows = [
        ['Asset Name', project.asset_name or '—'],
        ['Type of Structure', project.structure_type or '—'],
        ['Type of Inspection', project.inspection_type or '—'],
        ['Inspection Scope', scope],
        ['Location (Lat, Long)', f"{project.latitude:.5f}, {project.longitude:.5f}"],
        ['Total Findings Recorded', str(len(defects))],
    ]
    table_rows = [
        [Paragraph(label, styles['CoverDetailLabel']), Paragraph(value, styles['CoverDetailValue'])]
        for label, value in detail_rows
    ]
    detail_table = Table(table_rows, colWidths=[45 * mm, usable_w - 45 * mm])
    detail_table.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#dfe3ea')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f4f6f9')),
    ]))
    story.append(KeepTogether([Paragraph('Chimney Details', styles['CoverSectionHead']), detail_table]))
    story.append(PageBreak())
    return story


# ── Findings table pages ─────────────────────────────────────────────────────

def _defect_row(defect_dict, static_root, styles, seq_no, row_height):
    pos = defect_dict.get('position') or {}
    lat = pos.get('lat')
    lon = pos.get('lon')
    coord_str = f"{lat:.5f}, {lon:.5f}" if lat is not None and lon is not None else '—'
    direction = defect_dict.get('direction') or '—'
    coord_para = Paragraph(f"{coord_str}<br/><b>({direction})</b>", styles['CellText'])

    sev = defect_dict.get('severity') or 'Minor'
    sev_colors = {
        'Minor':    colors.HexColor('#1f9d68'),
        'Moderate': colors.HexColor('#b9821f'),
        'Critical': colors.HexColor('#c94b42'),
    }
    sev_color = sev_colors.get(sev, colors.HexColor('#333333'))
    sev_para = Paragraph(f'<font color="{sev_color.hexval()}"><b>{sev}</b></font>', styles['CellText'])

    defect_id_para = Paragraph(f"<b>D{seq_no}</b>", styles['CellText'])
    element_para   = Paragraph(defect_dict.get('title') or '—', styles['CellText'])
    type_para      = Paragraph(defect_dict.get('defect_type') or '—', styles['CellText'])
    height_para    = Paragraph(defect_dict.get('height') or '—', styles['CellText'])
    location_para  = Paragraph(defect_dict.get('location') or '—', styles['CellText'])
    area_para      = Paragraph(defect_dict.get('area') or '—', styles['CellText'])

    img_cell = Paragraph('No image', styles['CellText'])
    image_url = defect_dict.get('image_url') or ''
    if image_url:
        rel = image_url.lstrip('/')
        if rel.startswith('static/'):
            rel = rel[len('static/'):]
        full_path = os.path.join(static_root, rel)
        if os.path.exists(full_path):
            try:
                from PIL import Image as PILImage
                with PILImage.open(full_path) as pil_img:
                    pil_img.verify()
                # Cover-fit: crop the source image to exactly match the
                # cell's aspect ratio (center-crop, no distortion), then
                # size it to exactly fill the cell — so the photo touches
                # the cell's borders on every side with no gap, rather
                # than fitting-within and leaving empty space on one
                # axis. Cropped copy is written next to the source file
                # (report generation already writes into static_root, so
                # this is consistent with how the rest of the app treats
                # that folder) rather than overwriting the original.
                with PILImage.open(full_path) as pil_img:
                    pil_img = pil_img.convert('RGB')
                    iw, ih = pil_img.size
                    cell_aspect = row_height / IMAGE_CELL_AVAILABLE_W
                    src_aspect = ih / float(iw) if iw else cell_aspect
                    if src_aspect > cell_aspect:
                        # source is relatively taller than the cell — crop top/bottom
                        crop_h = int(iw * cell_aspect)
                        top = (ih - crop_h) // 2
                        cropped = pil_img.crop((0, top, iw, top + crop_h))
                    else:
                        # source is relatively wider than the cell — crop left/right
                        crop_w = int(ih / cell_aspect)
                        left = (iw - crop_w) // 2
                        cropped = pil_img.crop((left, 0, left + crop_w, ih))
                    crop_dir = os.path.join(static_root, 'uploads', 'report_crops')
                    os.makedirs(crop_dir, exist_ok=True)
                    crop_name = f"crop_{os.path.splitext(os.path.basename(full_path))[0]}_{seq_no}.jpg"
                    crop_path = os.path.join(crop_dir, crop_name)
                    cropped.save(crop_path, 'JPEG', quality=88)
                img_cell = Image(crop_path, width=IMAGE_CELL_AVAILABLE_W, height=row_height)
            except Exception:
                img_cell = Paragraph('Image unavailable', styles['CellText'])

    return [defect_id_para, element_para, type_para, sev_para,
            height_para, location_para, coord_para, area_para, img_cell]


def build_defect_report_pdf(project, defects, static_root, cover_image_path=None):
    """Return a BytesIO containing the finished PDF."""
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=10 * mm, rightMargin=10 * mm,
        topMargin=LOGO_HEADER_TOP_GAP + LOGO_HEADER_HEIGHT + 4 * mm, bottomMargin=14 * mm,
        title=f'{project.asset_name} — Chimney Inspection Report',
    )
    styles = _styles()
    story = []

    story.extend(_build_cover_page(project, defects, static_root, styles, cover_image_path))

    header_cols = ['Defect ID', 'Element', 'Type', 'Severity', 'Distance\nfrom Ground',
                   'Location', 'Coordinates\n(Direction)', 'Area', 'Image']
    # Scaled proportionally from the original widths to exactly fill the
    # page's usable width (190mm, with the 10mm/10mm margins above) —
    # so the table sits flush against both margins symmetrically,
    # instead of the old widths (summing to 172mm) leaving an
    # unaccounted, asymmetric gap on the right only.
    col_widths = [13.26 * mm, 26.51 * mm, 19.88 * mm, 15.47 * mm,
                  17.67 * mm, 22.09 * mm, 30.93 * mm, 15.47 * mm, 28.72 * mm]

    def make_title_block():
        story.append(Paragraph(
            'Chimney Defect List found by Drogo Aerospace',
            styles['ReportTitle']))
        story.append(Paragraph(
            'The following findings were identified during the drone-based 3D inspection survey of this structure.<br/>'
            'Each entry below includes its severity, exact location, and supporting photographic evidence.',
            styles['ReportSubtitle']))
        story.append(Spacer(1, 6 * mm))

    make_title_block()

    if not defects:
        story.append(Paragraph('No defects have been recorded for this chimney yet.', styles['CellTextLeft']))
    else:
        # First page: 7 defects (title block takes the rest of the room).
        # Every page after that: no title block at all, just the column
        # header + up to 8 defect rows, using the extra room that frees up.
        chunks = []
        if defects:
            chunks.append(defects[:DEFECTS_PER_PAGE_FIRST])
            rest = defects[DEFECTS_PER_PAGE_FIRST:]
            chunks.extend(rest[i:i + DEFECTS_PER_PAGE] for i in range(0, len(rest), DEFECTS_PER_PAGE))

        seq_no = 1
        for page_idx, chunk in enumerate(chunks):
            if not chunk:
                continue
            row_height = DEFECTS_ROW_HEIGHT if page_idx == 0 else DEFECTS_ROW_HEIGHT_NO_HEADING
            table_data = [header_cols]
            for d in chunk:
                table_data.append(_defect_row(d.to_dict(), static_root, styles, seq_no, row_height))
                seq_no += 1

            table = Table(table_data, colWidths=col_widths, repeatRows=1,
                          rowHeights=[DEFECTS_HEADER_ROW_HEIGHT] + [row_height] * len(chunk))
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1b1e24')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 7.5),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#c5cad4')),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f4f6f9')]),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                # Image column (index 8) — zero padding on its data rows
                # (not the header) so the cropped cover-fit photo touches
                # the cell's border lines on every side, no gap.
                ('LEFTPADDING', (8, 1), (8, -1), 0),
                ('RIGHTPADDING', (8, 1), (8, -1), 0),
                ('TOPPADDING', (8, 1), (8, -1), 0),
                ('BOTTOMPADDING', (8, 1), (8, -1), 0),
            ]))
            story.append(table)
            if page_idx < len(chunks) - 1:
                story.append(PageBreak())
                # No make_title_block() here — pages after the first are
                # just the defect table, no repeated heading.

    header_fn = _draw_page_header(static_root, getattr(project, 'client_logo_path', '') or '')
    doc.build(story, onFirstPage=header_fn, onLaterPages=header_fn)
    buf.seek(0)
    return buf
