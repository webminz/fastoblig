import sys
from dotenv import load_dotenv

print(sys.path)

load_dotenv()

import canvas

if __name__ == "__main__":
    courses = canvas.get_courses()
    for c in courses:
        print(f"{c.id}: ({c.code})'{c.description}'")

