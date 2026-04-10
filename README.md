# 📚 EduScheduler

**Αυτόματο Ωρολόγιο Πρόγραμμα για Σχολεία & Φροντιστήρια**

Δημιουργεί αυτοματοποιημένα βέλτιστα ωρολόγια προγράμματα, λαμβάνοντας υπόψη καθηγητές, μαθητές, αίθουσες και δεκάδες περιορισμούς.

## ✨ Χαρακτηριστικά

- 🧠 **Αυτόματη δημιουργία** ωρολογίου με AI/Constraint Solver (Google OR-Tools)
- 👨‍🏫 **Διαχείριση καθηγητών** — διαθεσιμότητα, φόρτος εργασίας, προτιμήσεις
- 📖 **Διαχείριση μαθημάτων** — ώρες/εβδομάδα, τύπος αίθουσας
- 🏫 **Διαχείριση αιθουσών** — χωρητικότητα, τύπος (εργαστήρια, γυμναστήρια)
- 📋 **Τάξεις & Τμήματα** — αριθμός μαθητών, ομάδες
- ⚙️ **Ευέλικτοι περιορισμοί** — σκληροί & μαλακοί, βαρύτητα
- 📊 **Οπτικοποίηση** — grid view ανά καθηγητή / τάξη / αίθουσα
- 🖨️ **Εξαγωγή** — PDF, Excel

## 🛠️ Tech Stack

- **Backend:** Python 3.12 + FastAPI
- **Solver:** Google OR-Tools CP-SAT
- **Database:** PostgreSQL
- **Frontend:** HTML/CSS/JS (Vanilla)
- **Deployment:** Docker Compose

## 🚀 Εγκατάσταση

### Με Docker (Προτεινόμενο)

```bash
# Clone
git clone https://github.com/panoscoolman-beep/EduScheduler.git
cd EduScheduler

# Αντέγραψε το env αρχείο
cp .env.example .env

# Ξεκίνα τα containers
docker-compose up -d
```

Η εφαρμογή θα είναι διαθέσιμη στο `http://localhost:8080`

### Τοπική Ανάπτυξη

```bash
# Backend
cd backend
python -m venv venv
source venv/bin/activate  # Linux/Mac
pip install -r requirements.txt
uvicorn main:app --reload

# Frontend
# Σερβίρεται αυτόματα από FastAPI static files
```

## 📁 Δομή Project

```
EduScheduler/
├── backend/
│   ├── main.py              # FastAPI entry point
│   ├── database.py          # Database connection
│   ├── models/              # Data models
│   ├── routers/             # API endpoints
│   └── solver/              # OR-Tools solver engine
├── frontend/
│   ├── index.html           # Main SPA
│   ├── css/styles.css       # Design system
│   └── js/                  # Application logic
├── docker-compose.yml       # Production deployment
├── Dockerfile               # Backend container
└── README.md
```

## 📄 Άδεια

MIT License
