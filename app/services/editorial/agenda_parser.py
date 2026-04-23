import html
import re
from typing import Any, Dict, List


DAY_PATTERN = (
    r"(?:DIVENDRES|DISSABTE|DIUMENGE|DILLUNS|DIMARTS|DIMECRES|DIJOUS)"
    r"(?:,?\s*\d{1,2}(?:\s*(?:de|d['’]))?\s*[A-ZÀ-Úa-zà-ú]+)?"
    r"(?:\s*(?:i|y)\s*(?:DIVENDRES|DISSABTE|DIUMENGE|DILLUNS|DIMARTS|DIMECRES|DIJOUS)"
    r"(?:,?\s*\d{1,2}(?:\s*(?:de|d['’]))?\s*[A-ZÀ-Úa-zà-ú]+)?)?"
)
SPACE_LABEL_PATTERN = r"(?:Sala|Espai|Zona|Biblioteca|Pla[çc]a|Riera|TMC|Pavell[oó]|Parc|Passeig|Recinte|Auditori|Food\s+Trucks|Estand|Diversos\s+espais|Davant\s+escola)"
SPACE_PATTERN = rf"{SPACE_LABEL_PATTERN}[^\n]*"
TIME_PATTERN = (
    r"(?:"
    r"A\s*partir\s+de\s+les\s+\d{1,2}(?::\d{2})?\s*h"
    r"|"
    r"(?:de\s+)?\d{1,2}(?::\d{2})?\s*h?\s*(?:a|-|–)\s*\d{1,2}(?::\d{2})?\s*h"
    r"(?:\s*i\s*de\s*\d{1,2}(?::\d{2})?\s*h?\s*(?:a|-|–)\s*\d{1,2}(?::\d{2})?\s*h)?"
    r"|"
    r"\d{1,2}(?::\d{2})?\s*h"
    r")"
)

DAY_RE = re.compile(rf"^{DAY_PATTERN}$", re.IGNORECASE)
SPACE_RE = re.compile(rf"^{SPACE_PATTERN}$", re.IGNORECASE)
TIME_RE = re.compile(TIME_PATTERN, re.IGNORECASE)
HIGHLIGHT_RE = re.compile(r"^(?:Destacat|Destacado)\s*:?\s*(.+)$", re.IGNORECASE)
EXTRA_INFO_RE = re.compile(r"\b(Gratu[iï]t|Inscripci[oó]\s+pr[eè]via|Inscripci[oó]|Obert\s+a\s+tothom)\b", re.IGNORECASE)
DAY_HINT_RE = re.compile(r"\b(?:DIVENDRES|DISSABTE|DIUMENGE|DILLUNS|DIMARTS|DIMECRES|DIJOUS)\b", re.IGNORECASE)


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalize_markdown_like_text(raw_text: str) -> str:
    text = str(raw_text or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("**", "")
    text = text.replace("__", "")
    text = text.replace("_", "")
    text = re.sub(r"([a-zà-ÿ])([A-ZÀ-Ý])", r"\1 \2", text)
    text = re.sub(r"([”\"'])([A-ZÀ-Ý])", r"\1 \2", text)
    return text


def _title_case_if_upper(value: str) -> str:
    cleaned = _clean_text(value)
    alpha = [char for char in cleaned if char.isalpha()]
    if alpha and sum(1 for char in alpha if char.isupper()) / len(alpha) >= 0.6:
        return cleaned.lower().capitalize()
    return cleaned


def _contains_time(value: str) -> bool:
    return bool(TIME_RE.search(value or ""))


def _is_day_line(value: str) -> bool:
    return bool(DAY_RE.match(_clean_text(value)))


def _is_space_line(value: str) -> bool:
    return bool(SPACE_RE.match(_clean_text(value)))


def _looks_like_event_heading(value: str) -> bool:
    cleaned = _clean_text(value)
    if not cleaned or _contains_time(cleaned) or _is_day_line(cleaned) or _is_space_line(cleaned):
        return False
    alpha = [char for char in cleaned if char.isalpha()]
    if not alpha:
        return False
    return sum(1 for char in alpha if char.isupper()) / len(alpha) >= 0.7


def _extract_extra_info(value: str) -> tuple[str, str]:
    matches = [match.group(1) for match in EXTRA_INFO_RE.finditer(value or "")]
    cleaned = EXTRA_INFO_RE.sub("", value or "")
    normalized = []
    seen = set()
    for item in matches:
        normalized_item = _clean_text(item)
        lower_item = normalized_item.lower()
        if lower_item in seen:
            continue
        normalized.append(normalized_item)
        seen.add(lower_item)
    return _clean_text(cleaned), " · ".join(normalized)


def _limit_sentences(value: str, max_sentences: int = 2) -> str:
    cleaned = _clean_text(value)
    if not cleaned:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    selected = [sentence for sentence in sentences if sentence][:max_sentences]
    return _clean_text(" ".join(selected) or cleaned)


def _paragraphs_from_text(text: str) -> List[str]:
    blocks = re.split(r"\n\s*\n+", str(text or "").replace("\r\n", "\n").replace("\r", "\n"))
    cleaned_blocks = [_clean_text(block) for block in blocks if _clean_text(block)]
    return _merge_broken_paragraphs(cleaned_blocks)


def _merge_broken_paragraphs(blocks: List[str]) -> List[str]:
    merged: List[str] = []
    for block in blocks:
        if merged and _should_merge_paragraphs(merged[-1], block):
            merged[-1] = _clean_text(f"{merged[-1]} {block}")
        else:
            merged.append(block)
    return merged


def _should_merge_paragraphs(previous: str, current: str) -> bool:
    if not previous or not current:
        return False
    if _is_day_line(current) or _is_space_line(current) or _contains_time(current):
        return False
    if current.isupper() and len(current.split()) <= 6:
        return False
    if previous.endswith((".", "!", "?")):
        return False
    if current[:1].islower():
        return True
    return previous.split()[-1].lower() in {"de", "del", "dels", "la", "les", "el", "els", "un", "una", "i", "amb", "per", "a", "en", "al", "que"}


def _merge_space_lines(lines: List[str]) -> List[str]:
    merged: List[str] = []
    index = 0
    while index < len(lines):
        current = lines[index]
        if current in {"Sala", "Espai", "Zona", "Plaça", "Placa", "Riera", "Biblioteca", "Estand"} and index + 1 < len(lines):
            next_line = lines[index + 1]
            if next_line and not _contains_time(next_line) and not _is_day_line(next_line) and not _is_space_line(next_line):
                merged.append(f"{current} {next_line}")
                index += 2
                continue
        merged.append(current)
        index += 1
    return merged


def _split_intro_from_preface(preface_lines: List[str]) -> tuple[List[str], List[str]]:
    lines = list(preface_lines or [])
    intro = []
    while len(lines) > 2 and lines and not _looks_like_event_heading(lines[0]):
        intro.append(lines.pop(0))
    return intro, lines


# Preprocesa el texto bruto para facilitar el parsing determinista.
def preprocess_agenda_text(raw_text: str) -> str:
    text = _normalize_markdown_like_text(raw_text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    text = re.sub(rf"(?<!\n)(?<! i )(?<! y )(?=\b{DAY_PATTERN}\b)", "\n", text, flags=re.IGNORECASE)
    text = re.sub(rf"(?<!\n)(?=\b{SPACE_LABEL_PATTERN}\b)", "\n", text, flags=re.IGNORECASE)
    text = _insert_time_breaks(text)
    text = re.sub(r"\n{2,}", "\n", text)
    text = re.sub(r" *\n *", "\n", text)
    return text.strip()


def _insert_time_breaks(text: str) -> str:
    pieces = []
    last_index = 0
    for match in TIME_RE.finditer(text):
        start = match.start()
        pieces.append(text[last_index:start])
        line_start = text.rfind("\n", 0, start) + 1
        prefix = text[line_start:start]
        prefix_clean = prefix.strip().lower()
        context_before = text[max(0, start - 32):start].lower()
        should_break = (
            start > 0
            and text[start - 1].isspace()
            and prefix.strip()
            and not DAY_HINT_RE.search(prefix)
            and not prefix.strip().endswith(("•", "-", "–"))
            and prefix_clean not in {"de", "i de", "de les", "a les"}
            and not re.search(r"(?:\b(?:a|de|i de|de les|a les)|-|–)\s*$", context_before)
        )
        if should_break and (not pieces[-1].endswith("\n")):
            pieces.append("\n")
        pieces.append(match.group(0))
        last_index = match.end()
    pieces.append(text[last_index:])
    return "".join(pieces)


# Divide un bloque con varias horas en eventos independientes sin perder la hora.
def split_events_by_time(block_text: str) -> List[str]:
    cleaned = _clean_text(block_text)
    if not cleaned:
        return []
    matches = list(TIME_RE.finditer(cleaned))
    if len(matches) <= 1:
        return [cleaned]

    if _looks_like_single_marked_event(cleaned, matches):
        return [cleaned]

    fragments = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(cleaned)
        fragment = _clean_text(cleaned[match.start():end])
        if fragment:
            fragments.append(fragment)
    return fragments or [cleaned]


def _looks_like_single_marked_event(value: str, matches: List[re.Match]) -> bool:
    marker = re.search(r"\s[\-–]\s", value)
    if not marker:
        return False

    marker_pos = marker.start()
    times_before = [match for match in matches if match.start() < marker_pos]
    times_after = [match for match in matches if match.start() > marker_pos]
    return bool(times_before) and not times_after


# Normaliza un fragmento usando el contexto de dia y espacio ya detectado.
def normalize_event(fragment: str, context: Dict[str, str]) -> Dict[str, str]:
    lines = [_clean_text(line) for line in str(fragment or "").splitlines() if _clean_text(line)]
    text = "\n".join(lines)
    datetime_match = TIME_RE.search(text)
    datetime_label = _clean_text(datetime_match.group(0)) if datetime_match else ""

    explicit_location = ""
    content_lines: List[str] = []
    extra_info_parts: List[str] = []
    for line in lines:
        if _is_day_line(line):
            continue
        if _is_space_line(line):
            explicit_location = explicit_location or line
            continue
        cleaned_line, line_extra_info = _extract_extra_info(line)
        if line_extra_info:
            extra_info_parts.append(line_extra_info)
        if cleaned_line and not (_contains_time(cleaned_line) and DAY_HINT_RE.search(cleaned_line)):
            content_lines.append(cleaned_line)

    content_text = " ".join(content_lines)
    if datetime_label:
        content_text = _clean_text(TIME_RE.sub("", content_text, count=1))
    content_text = re.sub(r"^[\-–—]\s*", "", content_text)

    if not explicit_location:
        location_match = re.search(r"\b(?:a\s+la|al|a\s+l')\s+(.+)$", content_text, re.IGNORECASE)
        if location_match:
            explicit_location = _clean_text(location_match.group(1))
            content_text = _clean_text(content_text[:location_match.start()])

    content_text, extracted_extra_info = _extract_extra_info(content_text)
    title = content_text
    description = ""
    if content_lines:
        heading_line = ""
        main_line = content_lines[0]
        remaining_lines = content_lines[1:]
        if _looks_like_event_heading(main_line) and remaining_lines:
            heading_line = _title_case_if_upper(main_line)
            title = remaining_lines[0]
            description = " ".join(remaining_lines[1:])
        else:
            title = main_line
            description = " ".join(remaining_lines)
        if heading_line:
            extra_info_parts.append(heading_line)

    if datetime_label:
        title = _clean_text(TIME_RE.sub("", title, count=1))
        description = _clean_text(TIME_RE.sub("", description, count=1))

    if extracted_extra_info:
        extra_info_parts.append(extracted_extra_info)

    return {
        "day": _title_case_if_upper(context.get("current_day", "")),
        "space": _clean_text(context.get("current_space", "")),
        "title": _clean_text(title),
        "datetime_label": datetime_label,
        "location": explicit_location or _clean_text(context.get("current_space", "")),
        "description": _limit_sentences(description),
        "extra_info": _clean_text(" · ".join(part for part in extra_info_parts if part)),
    }


# Parsea todo el texto de agenda y devuelve estructura intermedia determinista.
def parse_agenda(raw_text: str) -> Dict[str, Any]:
    normalized_raw = str(raw_text or "").replace("\r\n", "\n").replace("\r", "\n")
    highlight_match = re.search(r"(?ims)^DESTACAT:?\s*$\s*(.+)$", normalized_raw)
    highlight_text = _clean_text(highlight_match.group(1)) if highlight_match else ""
    raw_without_highlight = normalized_raw[:highlight_match.start()].strip() if highlight_match else normalized_raw

    program_match = re.search(r"(?im)^PROGRAMACI[ÓO]\s*$", raw_without_highlight)
    intro_source = raw_without_highlight[:program_match.start()].strip() if program_match else ""
    program_source = raw_without_highlight[program_match.end():].strip() if program_match else raw_without_highlight

    supplementary_match = re.search(r"(?im)^(ACTIVITATS CONT[IÍ]NUES|ESPAIS COMPLEMENTARIS)\s*$", program_source)
    trailing_source = program_source[supplementary_match.start():].strip() if supplementary_match else ""
    program_main_source = program_source[:supplementary_match.start()].strip() if supplementary_match else program_source

    text = preprocess_agenda_text(program_main_source)
    lines = _merge_space_lines([_clean_text(line) for line in text.split("\n") if _clean_text(line)])
    parsed: Dict[str, Any] = {"intro": [], "highlights": [], "events": [], "trailing": []}
    context = {"current_day": "", "current_space": ""}
    preface_lines: List[str] = []
    current_event_lines: List[str] = []

    if intro_source:
        parsed["intro"] = _paragraphs_from_text(intro_source)
    if trailing_source:
        parsed["trailing"] = _merge_space_lines([_clean_text(line) for line in trailing_source.split("\n") if _clean_text(line)])
    if highlight_text:
        parsed["highlights"].append(_limit_sentences(highlight_text, max_sentences=2))

    def flush_current_event() -> None:
        nonlocal current_event_lines
        if not current_event_lines:
            return
        event = normalize_event("\n".join(current_event_lines), context)
        if event.get("title") or event.get("description"):
            parsed["events"].append(event)
        current_event_lines = []

    for line in lines:
        if _is_day_line(line):
            flush_current_event()
            if preface_lines:
                parsed["trailing"].extend(preface_lines)
            preface_lines = []
            context["current_day"] = line
            continue

        if _is_space_line(line):
            if current_event_lines and not context.get("current_space"):
                current_event_lines.append(line)
                flush_current_event()
                context["current_space"] = line
                continue
            flush_current_event()
            if preface_lines:
                parsed["trailing"].extend(preface_lines)
                preface_lines = []
            context["current_space"] = line
            continue

        if _contains_time(line):
            flush_current_event()
            fragments = split_events_by_time(line)
            if len(fragments) > 1:
                first_prefix = preface_lines
                if not parsed["events"] and not parsed["intro"]:
                    intro_lines, first_prefix = _split_intro_from_preface(first_prefix)
                    parsed["intro"].extend(intro_lines)
                preface_lines = []
                for index, fragment in enumerate(fragments):
                    lines_for_event = []
                    if index == 0 and first_prefix:
                        lines_for_event.extend(first_prefix)
                    lines_for_event.append(fragment)
                    event = normalize_event("\n".join(lines_for_event), context)
                    if event.get("title") or event.get("description"):
                        parsed["events"].append(event)
                continue

            current_event_prefix = preface_lines
            if not parsed["events"] and not parsed["intro"]:
                intro_lines, current_event_prefix = _split_intro_from_preface(current_event_prefix)
                parsed["intro"].extend(intro_lines)
            current_event_lines = current_event_prefix + [line]
            preface_lines = []
            continue

        if current_event_lines:
            if _looks_like_event_heading(line):
                flush_current_event()
                preface_lines = [line]
            else:
                current_event_lines.append(line)
            continue

        preface_lines.append(line)

    flush_current_event()
    if preface_lines and not parsed["events"] and not parsed["intro"]:
        parsed["intro"].extend(preface_lines)
    elif preface_lines:
        parsed["trailing"].extend(preface_lines)
    return parsed


def agenda_events_to_content_items(events: List[Dict[str, str]]) -> List[Dict[str, str]]:
    return [
        {
            "title": _clean_text(event.get("title", "")),
            "datetime_label": _clean_text(event.get("datetime_label", "")),
            "location": _clean_text(event.get("location", "")),
            "description": _clean_text(event.get("description", "")),
            "extra_info": _clean_text(event.get("extra_info", "")),
            "image_ref": "",
        }
        for event in events
        if _clean_text(event.get("title", "")) or _clean_text(event.get("description", ""))
    ]


def render_highlight_box(text: str) -> str:
    return f'<p class="highlight-box"><strong><em>{html.escape(_limit_sentences(text, max_sentences=2))}</em></strong></p>'


# Renderiza HTML legible agrupando por dia y espacio.
def render_agenda_html(events: List[Dict[str, str]]) -> str:
    html_parts: List[str] = []
    current_day = None
    current_space = None

    for event in events:
        day = _clean_text(event.get("day", ""))
        space = _clean_text(event.get("space", ""))
        if day and day != current_day:
            html_parts.append(f'<h2 class="agenda-day">{html.escape(day)}</h2>')
            current_day = day
            current_space = None
        if space and space != current_space:
            html_parts.append(f'<h3 class="agenda-space">{html.escape(space)}</h3>')
            current_space = space

        html_parts.append(f'<h4 class="agenda-title">{html.escape(_clean_text(event.get("title", "")))}</h4>')
        if event.get("datetime_label"):
            html_parts.append(f'<p class="agenda-datetime"><strong><em>Data i hora:</em></strong> {html.escape(_clean_text(event.get("datetime_label", "")))}</p>')
        if event.get("location"):
            html_parts.append(f'<p class="agenda-location"><strong><em>Lloc:</em></strong> {html.escape(_clean_text(event.get("location", "")))}</p>')
        if event.get("description"):
            html_parts.append(f'<p class="agenda-description">{html.escape(_clean_text(event.get("description", "")))}</p>')
        if event.get("extra_info"):
            html_parts.append(f'<p class="agenda-extra"><strong>Informació addicional:</strong> {html.escape(_clean_text(event.get("extra_info", "")))}</p>')

    return "\n".join(html_parts)
