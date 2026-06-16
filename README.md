# CV Standardizer

An AI-powered desktop application that reads PDF CVs and automatically generates clean, professionally designed standardized CV documents using Google Gemini.

## What it does

- Accepts a folder of PDF CV files as input
- Sends each CV directly to Google Gemini for intelligent analysis
- Extracts: Name, Email, Skills, Education, Work Experience, Achievements, Certificates, Trainings, Publications
- Generates one professionally designed PDF per candidate with smart two-column layout
- Saves all extracted data into a combined JSON file

## Features

- Direct PDF analysis by Gemini AI — no text extraction needed
- Custom branded PDF output with your logo
- Smart column balancing — content distributed evenly between left and right
- Rounded skill tags layout for visual clarity
- Multi-page support with correct column continuity
- Automatic retry on API rate limits and server errors
- Simple Tkinter desktop UI — no browser, no server needed

## Tech Stack

| Tool | Purpose |
|---|---|
| Python 3.11+ | Core language |
| Google Gemini API | CV analysis and data extraction |
| ReportLab | PDF generation |
| PyMuPDF | PDF merging |
| Tkinter | Desktop UI |

## Setup

```bash
git clone https://github.com/yourusername/cv-standardizer.git
cd cv-standardizer
pip install -r requirements.txt
```

Add your Gemini API key to `.env`:

```env
GEMINI_API_KEY=your_key_here
GEMINI_MODEL=gemini-2.5-flash
MAX_CV_TEXT_CHARS=25000
RETRY_MAX_ATTEMPTS=5
RETRY_INITIAL_WAIT=15
```

Convert the custom font (one time only):

```bash
python convert_font.py
```

Run the app:

```bash
python run.py
```

## Output

```
output/
├── all_cvs.json
├── Candidate_One_CV.pdf
├── Candidate_Two_CV.pdf
└── Candidate_Three_CV.pdf
```

## License

MIT
