import os
import io
import requests
import streamlit as st
from openai import OpenAI
from PIL import Image
from dotenv import load_dotenv

load_dotenv(".env")

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(page_title="OpenAI Image Studio", layout="centered")
st.title("OpenAI Image Studio")

# ── Sidebar – API key & model ─────────────────────────────────────────────────
with st.sidebar:
    st.header("Settings")

    api_key = st.text_input(
        "OpenAI API Key",
        value=os.getenv("OPENAI_API_KEY", ""),
        type="password",
    )

    model = st.selectbox(
        "Image Model",
        options=["dall-e-3", "dall-e-2", "gpt-image-1"],
        index=0,
    )

    # Size options vary by model
    size_options = {
        "dall-e-3": ["1024x1024", "1792x1024", "1024x1792"],
        "dall-e-2": ["256x256", "512x512", "1024x1024"],
        "gpt-image-1": ["1024x1024", "1792x1024", "1024x1792"],
    }
    size = st.selectbox("Size", options=size_options[model])

    # dall-e-3 / gpt-image-1 extras
    quality = None
    style = None
    if model in ("dall-e-3", "gpt-image-1"):
        quality = st.selectbox("Quality", ["standard", "hd"])
        style = st.selectbox("Style", ["vivid", "natural"])

    st.divider()
    st.caption("Variations and Edit require dall-e-2")

# ── Client ────────────────────────────────────────────────────────────────────
def get_client():
    if not api_key:
        st.error("Enter your OpenAI API key in the sidebar.")
        st.stop()
    return OpenAI(api_key=api_key)

# ── Prompts (shared across tabs) ───────────────────────────────────────────────
st.subheader("Prompts")
system_prompt = st.text_area(
    "System Prompt  (style / context prefix)",
    value="Photorealistic digital art, high detail, vibrant colors.",
    height=80,
)
user_prompt = st.text_area(
    "User Prompt",
    value="A cyberpunk monkey hacker dreaming of a beautiful bunch of bananas",
    height=80,
)

def build_prompt():
    parts = [p.strip() for p in [system_prompt, user_prompt] if p.strip()]
    return ". ".join(parts)

# ── Tabs ───────────────────────────────────────────────────────────────────────
tab_gen, tab_var, tab_edit = st.tabs(["Generate", "Variations", "Edit"])

# ── Generate ──────────────────────────────────────────────────────────────────
with tab_gen:
    st.markdown("Generate a new image from the prompts above.")
    if st.button("Generate Image", type="primary"):
        client = get_client()
        full_prompt = build_prompt()
        st.caption(f"Full prompt: *{full_prompt}*")
        with st.spinner("Generating…"):
            kwargs = dict(
                model=model,
                prompt=full_prompt,
                n=1,
                size=size,
                response_format="url",
            )
            if quality:
                kwargs["quality"] = quality
            if style:
                kwargs["style"] = style
            try:
                resp = client.images.generate(**kwargs)
                url = resp.data[0].url
                img_bytes = requests.get(url).content
                st.image(img_bytes, use_container_width=True)
                st.session_state["last_image_bytes"] = img_bytes
                st.download_button("Download", img_bytes, file_name="generated.png", mime="image/png")
            except Exception as e:
                st.error(f"Generation failed: {e}")

# ── Variations ────────────────────────────────────────────────────────────────
with tab_var:
    st.markdown("Generate variations of an existing image. **Requires dall-e-2.**")
    uploaded = st.file_uploader("Upload source image (PNG, square, <4 MB)", type=["png"], key="var_upload")

    # Offer the last generated image as a shortcut
    if "last_image_bytes" in st.session_state:
        if st.checkbox("Use last generated image instead"):
            uploaded_bytes = st.session_state["last_image_bytes"]
            st.image(uploaded_bytes, width=256, caption="Source image")
        else:
            uploaded_bytes = uploaded.read() if uploaded else None
    else:
        uploaded_bytes = uploaded.read() if uploaded else None

    num_var = st.slider("Number of variations", 1, 4, 2)

    if st.button("Generate Variations", type="primary"):
        if not uploaded_bytes:
            st.warning("Upload a source image first.")
        else:
            client = get_client()
            cols = st.columns(num_var)
            with st.spinner("Generating variations…"):
                for i in range(num_var):
                    try:
                        resp = client.images.create_variation(
                            image=io.BytesIO(uploaded_bytes),
                            model="dall-e-2",
                            n=1,
                            size=size if size in ("256x256", "512x512", "1024x1024") else "1024x1024",
                            response_format="url",
                        )
                        img_bytes = requests.get(resp.data[0].url).content
                        cols[i].image(img_bytes, use_container_width=True, caption=f"Variation {i+1}")
                        cols[i].download_button(
                            "Download", img_bytes,
                            file_name=f"variation_{i+1}.png",
                            mime="image/png",
                            key=f"dl_var_{i}",
                        )
                    except Exception as e:
                        cols[i].error(str(e))

# ── Edit ──────────────────────────────────────────────────────────────────────
with tab_edit:
    st.markdown(
        "Edit part of an image using a mask. **Requires dall-e-2.**  "
        "The mask must be a PNG with transparent pixels where you want edits applied."
    )
    edit_img = st.file_uploader("Upload image to edit (PNG, square, <4 MB)", type=["png"], key="edit_img")
    mask_choice = st.radio("Mask", ["Auto-generate bottom-half mask", "Upload custom mask"])
    edit_mask = None
    if mask_choice == "Upload custom mask":
        edit_mask = st.file_uploader("Upload mask (PNG, same size, transparent = edit area)", type=["png"], key="edit_mask")

    if st.button("Edit Image", type="primary"):
        if not edit_img:
            st.warning("Upload an image to edit first.")
        else:
            client = get_client()
            img_bytes = edit_img.read()

            # Build mask
            if mask_choice == "Auto-generate bottom-half mask":
                img = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
                w, h = img.size
                mask_img = Image.new("RGBA", (w, h), (0, 0, 0, 255))
                for x in range(w):
                    for y in range(h // 2, h):
                        mask_img.putpixel((x, y), (0, 0, 0, 0))
                mask_buf = io.BytesIO()
                mask_img.save(mask_buf, format="PNG")
                mask_buf.seek(0)
                mask_bytes = mask_buf
            else:
                if not edit_mask:
                    st.warning("Upload a mask PNG.")
                    st.stop()
                mask_bytes = io.BytesIO(edit_mask.read())

            edit_size = size if size in ("256x256", "512x512", "1024x1024") else "1024x1024"
            full_prompt = build_prompt()
            st.caption(f"Edit prompt: *{full_prompt}*")
            with st.spinner("Editing…"):
                try:
                    resp = client.images.edit(
                        image=io.BytesIO(img_bytes),
                        mask=mask_bytes,
                        prompt=full_prompt,
                        model="dall-e-2",
                        n=1,
                        size=edit_size,
                        response_format="url",
                    )
                    result_bytes = requests.get(resp.data[0].url).content
                    col1, col2 = st.columns(2)
                    col1.image(img_bytes, use_container_width=True, caption="Original")
                    col2.image(result_bytes, use_container_width=True, caption="Edited")
                    st.download_button("Download edited", result_bytes, file_name="edited.png", mime="image/png")
                except Exception as e:
                    st.error(f"Edit failed: {e}")
