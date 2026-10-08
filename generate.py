
from PIL import Image, ImageDraw

# 1. Blank Certificate Image create panrom (Width: 800, Height: 600)
width, height = 800, 600
image = Image.new("RGB", (width, height), color="white")

# 2. Draw object create panrom
draw = ImageDraw.Draw(image)

# 3. Title text ezhuthuvom
title_text = "CERTIFICATE OF APPRECIATION"
draw.text((200, 100), title_text, fill="navy")

# 4. Participant Name ezhuthuvom
participant_name = "Rahul Kumar"
draw.text((250, 250), f"This is proudly presented to:\n\n{participant_name}", fill="black")

# 5. Image-a save panrom
image.save("sample_certificate.png")
print("Success! Certificate generated and saved.")