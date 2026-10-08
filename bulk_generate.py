import openpyxl
from PIL import Image, ImageDraw

# 1. Excel file-a open panrom
wb = openpyxl.load_workbook('students.xlsx')
sheet = wb.active

# 2. Excel sheet rows-a loop panrom
for row in sheet.iter_rows(min_row=2, values_only=True):
    name = row[0]  # Name mattum edukkrom
    
    if name:
        # 3. Real certificate template image-a load panrom
        try:
            image = Image.open('template.jpg')
        except FileNotFoundError:
            print("Error: 'template.jpg' file kidaikkavillai!")
            break
            
        draw = ImageDraw.Draw(image)
        
        # 4. ERASER TRICK: Pazhaya peru irukkira edathula oru white box-a podrom
        # (Note: Intha numbers (x1, y1, x2, y2) unga certificate-la peru enge irukkuko athuku etra pola small adjustments pannanum)
        # Example coordinates for name area:
        draw.rectangle([350, 420, 650, 480], fill="white")
        
        # 5. Puthu peria antha white box mela clear-ah print panrom
        draw.text((360, 430), f"{name}", fill="navy")
        
        # 6. Output certificate-a save panrom
        filename = f"certificate_{name}.png"
        image.save(filename)
        print(f"Certificate generated for: {name}")

print("\nElla certificates-um unga real template-oda successfully generate aagiduchu!")