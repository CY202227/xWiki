"""Image helpers for markdown ingestion."""

from __future__ import annotations

import base64
import re


def strip_embedded_base64_images(text: str) -> str:
  """Replace inline base64 image blocks with a stable placeholder."""
  text = re.sub(r"!\[.*?\]\(data:image\/.*?;base64,.*?\)", "[IMAGE_REMOVED]", text)
  text = re.sub(r"src=\"data:image\/.*?;base64,.*?\"", 'src="[IMAGE_REMOVED]"', text)
  text = re.sub(r"data:image\/.*?;base64,[A-Za-z0-9+/=\n\r]+", "[BASE64_DATA_REMOVED]", text)
  return text


def looks_like_base64_blob(text: str) -> bool:
  # heuristic for corrupted inline embedding
  sample = "".join(text.split())
  return (
      sample.startswith("iVBORw0KGgo") or
      sample.startswith("/9j/")
      or sample.startswith("Qk")
  )


def save_base64_image_if_possible(tag: str, output_dir) -> str | None:
  match = re.match(r"data:image/(.*?);base64,(.*)", tag, re.IGNORECASE)
  if not match:
    return None
  ext = match.group(1).split(";")[0] or "png"
  data = match.group(2)
  try:
    payload = base64.b64decode(data, validate=True)
  except Exception:
    return None
  output_dir.mkdir(parents=True, exist_ok=True)
  output = output_dir / f"image.{ext}"
  output.write_bytes(payload)
  return str(output.relative_to(output.parent.parent))
