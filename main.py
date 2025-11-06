import os
import json
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from kivy.app import App
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.spinner import Spinner
from kivy.uix.popup import Popup
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.recycleview import RecycleView
from kivy.properties import ListProperty
from kivy.clock import Clock
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from android.permissions import request_permissions, Permission  # type: ignore
import asyncio
import platform

# File storage setup
BASE_DIR = Path(os.path.expanduser("~/.fieldtests"))
CURVES_DIR = BASE_DIR / "Curves"
FORMS_DIR = BASE_DIR / "Forms"
ARCHIVED_CURVES_DIR = BASE_DIR / "ArchivedCurves"
ARCHIVED_FORMS_DIR = BASE_DIR / "ArchivedForms"
RECENT_ENTRIES_FILE = BASE_DIR / "recent_entries.json"
GENERAL_INFO_FILE = BASE_DIR / "general_info.json"

for d in [BASE_DIR, CURVES_DIR, FORMS_DIR, ARCHIVED_CURVES_DIR, ARCHIVED_FORMS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# Passcodes (hashed for security)
ADMIN_PASSCODE_HASH = hashlib.sha256("1984".encode()).hexdigest()
MASTER_PASSCODE_HASH = hashlib.sha256("1776".encode()).hexdigest()

# Recent entries storage
def load_recent_entries():
    if RECENT_ENTRIES_FILE.exists():
        with open(RECENT_ENTRIES_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_recent_entry(field, value):
    recent = load_recent_entries()
    if field not in recent:
        recent[field] = []
    if value and value not in recent[field]:
        recent[field].insert(0, value)
        recent[field] = recent[field][:5]
        with open(RECENT_ENTRIES_FILE, 'w') as f:
            json.dump(recent, f)

# Auto-complete TextInput
class AutoCompleteTextInput(TextInput):
    def __init__(self, field_name, **kwargs):
        super().__init__(**kwargs)
        self.field_name = field_name
        self.bind(focus=self.show_suggestions)

    def show_suggestions(self, instance, value):
        if value:
            suggestions = load_recent_entries().get(self.field_name, [])
            if suggestions:
                content = BoxLayout(orientation='vertical')
                for s in suggestions:
                    btn = Button(text=s, size_hint_y=None, height=40)
                    btn.bind(on_press=lambda x, s=s: self.select_suggestion(s))
                    content.add_widget(btn)
                popup = Popup(title='Recent Entries', content=content, size_hint=(0.5, 0.5))
                popup.open()

    def select_suggestion(self, value):
        self.text = value
        self.focus = False

# Main App
class FieldTestsApp(App):
    def build(self):
        self.sm = ScreenManager()
        self.sm.add_widget(HomeScreen(name='home'))
        self.sm.add_widget(CurvesScreen(name='curves'))
        self.sm.add_widget(FormsScreen(name='forms'))
        self.sm.add_widget(ArchiveScreen(name='archive'))
        self.sm.add_widget(AdminScreen(name='admin'))
        self.sm.add_widget(FormScreen(name='form'))
        self.sm.add_widget(MoistureTestScreen(name='moisture_test'))
        self.sm.add_widget(DeflectionTestScreen(name='deflection_test'))
        self.sm.add_widget(AddCurveScreen(name='add_curve'))
        self.sm.add_widget(ArchivedCurvesScreen(name='archived_curves'))
        self.sm.add_widget(ArchivedFormsScreen(name='archived_forms'))
        request_permissions([Permission.WRITE_EXTERNAL_STORAGE, Permission.READ_EXTERNAL_STORAGE])
        return self.sm

# Home Screen
class HomeScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        layout = BoxLayout(orientation='vertical', padding=10, spacing=10)
        self.date = datetime.now().strftime("%Y%m%d_%H%M")
        layout.add_widget(Label(text=f"Date: {self.date}"))
        self.inspector_name = TextInput(hint_text="Inspector Name")
        self.inspector_initials = TextInput(hint_text="Initials (e.g., JL)")
        self.district = TextInput(hint_text="District")
        layout.add_widget(self.inspector_name)
        layout.add_widget(self.inspector_initials)
        layout.add_widget(self.district)
        for btn in [("Curves", 'curves'), ("Forms", 'forms'), ("Archives", 'archive'), ("Admin", 'admin_passcode')]:
            layout.add_widget(Button(text=btn[0], on_press=lambda x, s=btn[1]: self.go_to(s)))
        self.add_widget(layout)

    def go_to(self, screen):
        if screen == 'admin_passcode':
            self.show_passcode_popup('admin')
        else:
            self.manager.current = screen

    def show_passcode_popup(self, target):
        content = BoxLayout(orientation='vertical')
        passcode = TextInput(hint_text="Enter Passcode", password=True)
        content.add_widget(passcode)
        content.add_widget(Button(text="Submit", on_press=lambda x: self.verify_passcode(passcode.text, target)))
        Popup(title="Passcode", content=content, size_hint=(0.5, 0.5)).open()

    def verify_passcode(self, passcode, target):
        if hashlib.sha256(passcode.encode()).hexdigest() == ADMIN_PASSCODE_HASH:
            self.manager.current = target
        elif target == 'change_passcode' and hashlib.sha256(passcode.encode()).hexdigest() == MASTER_PASSCODE_HASH:
            self.show_change_passcode_popup()
        else:
            Popup(title="Error", content=Label(text="Invalid Passcode"), size_hint=(0.5, 0.3)).open()

    def save_general_info(self):
        info = {
            "inspector_name": self.inspector_name.text,
            "inspector_initials": self.inspector_initials.text,
            "district": self.district.text,
            "date": self.date
        }
        with open(GENERAL_INFO_FILE, 'w') as f:
            json.dump(info, f)
        
# Curves Screen
class CurvesScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        layout = BoxLayout(orientation='vertical')
        self.rv = RecycleView()
        self.rv.data = []
        layout.add_widget(TextInput(hint_text="Search", on_text=self.search))
        layout.add_widget(self.rv)
        layout.add_widget(Button(text="Home", on_press=self.go_home))
        self.add_widget(layout)
        self.load_curves()

    def go_home(self, instance):
        self.manager.current = 'home'

    def load_curves(self):
        self.rv.data = [
            {"text": f"{c['name']} | {c['source']} | {c['sample_id']} | {c['ngi']}", "curve": c}
            for c in [json.load(open(f)) for f in CURVES_DIR.glob("*.json")]
        ]

    def search(self, instance):
        term = instance.text.lower()
        self.rv.data = [
            d for d in self.load_curves.__self__.rv.data
            if term in d["text"].lower()
        ]

# Forms Screen
class FormsScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        layout = BoxLayout(orientation='vertical')
        self.rv = RecycleView()
        self.rv.data = []
        layout.add_widget(TextInput(hint_text="Search by ID/Name/Date", on_text=self.search))
        layout.add_widget(self.rv)
        layout.add_widget(Button(text="Create New Form", on_press=self.create_form))
        layout.add_widget(Button(text="Archive Selected", on_press=self.archive_forms))
        layout.add_widget(Button(text="Home", on_press=self.go_home))
        self.add_widget(layout)
        self.load_forms()

    def go_home(self, instance):
        self.manager.current = 'home'

    def load_forms(self):
        forms = []
        for f in FORMS_DIR.glob("*.json"):
            form = json.load(open(f))
            last_update = datetime.fromisoformat(form['last_update'])
            age = datetime.now() - last_update
            color = "#FFFFFF"
            if form['status'] == "Incomplete":
                if age > timedelta(weeks=1):
                    color = "#FF0000"
                elif age > timedelta(days=3):
                    color = "#FFA500"
                elif age > timedelta(hours=24):
                    color = "#FFFF00"
            forms.append({
                "text": f"{form['form_id']} | {form['status']} | {form['inspector_name']} | {form['date']}",
                "form": form,
                "color": color
            })
        forms.sort(key=lambda x: (
            {"Incomplete": 0, "Pending": 1, "Complete": 2}[x["form"]["status"]],
            x["form"]["date"]
        ))
        self.rv.data = forms

    def search(self, instance):
        term = instance.text.lower()
        self.rv.data = [
            d for d in self.load_forms.__self__.rv.data
            if term in d["text"].lower()
        ]

    def create_form(self, instance=None):
        info = json.load(open(GENERAL_INFO_FILE))
        counter = len(list(FORMS_DIR.glob(f"F{info['inspector_initials']}*.json"))) + 1
        form_id = f"F{info['inspector_initials']}{datetime.now().strftime('%Y%m%d_%H%M')}_{counter}"
        form = {
            "form_id": form_id,
            "date": datetime.now().isoformat(),
            "last_update": datetime.now().isoformat(),
            "inspector_name": info["inspector_name"],
            "project_no": "",
            "contract_no": "",
            "curve_name": "",
            "status": "Incomplete",
            "tests": [],
            "moisture_result": "Pending",
            "deflection_result": "Pending",
            "overall_result": "Pending",
            "close_reason": ""
        }
        form_dir = FORMS_DIR / form_id
        form_dir.mkdir(exist_ok=True)
        with open(form_dir / "form.json", 'w') as f:
            json.dump(form, f)
        self.manager.get_screen('form').load_form(form_id)
        self.manager.current = 'form'

# Form Screen
class FormScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.layout = BoxLayout(orientation='vertical', padding=10, spacing=10)
        self.add_widget(self.layout)

    def go_home(self, instance):
        self.manager.current = 'home'

    def load_form(self, form_id):
        self.layout.clear_widgets()
        form_path = FORMS_DIR / form_id / "form.json"
        self.form = json.load(open(form_path))
        self.layout.add_widget(Label(text=f"Form ID: {self.form['form_id']}"))
        self.layout.add_widget(Label(text=f"Date: {self.form['date']}"))
        self.inspector_name = AutoCompleteTextInput("inspector_name", text=self.form['inspector_name'])
        self.project_no = AutoCompleteTextInput("project_no", text=self.form['project_no'])
        self.contract_no = AutoCompleteTextInput("contract_no", text=self.form['contract_no'])
        self.curve_name = Spinner(values=[c.stem for c in CURVES_DIR.glob("*.json")])
        self.curve_name.bind(text=self.load_curve_data)
        for w in [self.inspector_name, self.project_no, self.contract_no, self.curve_name]:
            self.layout.add_widget(w)
        self.curve_data_labels = {}
        for field in ["soil_type", "source", "sample_id", "ngi", "target_dtv", "optimum_moisture", "moisture_limits", "notes"]:
            self.curve_data_labels[field] = Label(text=f"{field.replace('_', ' ').title()}:")
            self.layout.add_widget(self.curve_data_labels[field])
        self.layout.add_widget(Label(text=f"Moisture Result: {self.form['moisture_result']}"))
        self.layout.add_widget(Label(text=f"Deflection Result: {self.form['deflection_result']}"))
        self.layout.add_widget(Label(text=f"Overall Result: {self.form['overall_result']}"))
        self.layout.add_widget(Label(text=f"Status: {self.form['status']}"))
        test_types = ["Moisture", "Deflection"]
        for t in self.form['tests']:
            test_types.remove(t['type'])
        self.test_type = Spinner(values=test_types)
        self.layout.add_widget(self.test_type)
        self.layout.add_widget(Button(text="Close Form", on_press=self.close_form))
        if self.form['status'] == "Pending":
            self.layout.add_widget(Button(text="Complete Form", on_press=self.complete_form))
        self.layout.add_widget(Button(text="Submit Test", on_press=self.submit_test))
        self.layout.add_widget(Button(text="Home", on_press=self.go_home))

    # ... rest of FormScreen continues in Part 4 …
# Moisture Test Screen
class MoistureTestScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.layout = BoxLayout(orientation='vertical', padding=10, spacing=10)
        self.add_widget(self.layout)

    def go_back(self, instance):
        self.manager.current = 'form'

    def go_home(self, instance):
        self.manager.current = 'home'

    def load_test(self, form_id):
        self.form_id = form_id
        self.layout.clear_widgets()
        curve = json.load(open(CURVES_DIR / json.load(open(FORMS_DIR / form_id / "form.json"))['curve_name'] + ".json"))
        self.test_id = f"T{form_id[1:]}_M"
        self.layout.add_widget(Label(text=f"Test ID: {self.test_id}"))
        for field in ["soil_type", "source", "optimum_moisture", "moisture_limits"]:
            self.layout.add_widget(Label(text=f"{field.replace('_', ' ').title()}: {curve[field]}"))
        self.station = AutoCompleteTextInput("station")
        self.feet_cl = AutoCompleteTextInput("feet_cl")
        self.depth = TextInput(hint_text="Depth Below Finish Grade")
        self.canister = TextInput(hint_text="Canister #")
        self.test_method = Spinner(values=["Oven", "Stove", "Speedy"])
        self.wet_weight = TextInput(hint_text="Wet Weight (g)")
        self.intermediate_weights = [TextInput(hint_text=f"Intermediate Weight {i+1} (g)") for i in range(8)]
        self.dry_weight = TextInput(hint_text="Dry Weight (g)")
        self.loss = Label(text="Loss: ")
        self.moisture_content = Label(text="Moisture Content: ")
        self.result = Label(text="Result: ")
        self.notes = TextInput(hint_text="Notes")
        for w in [self.station, self.feet_cl, self.depth, self.canister, self.test_method, self.wet_weight]:
            self.layout.add_widget(w)
        for i, w in enumerate(self.intermediate_weights):
            w.bind(text=lambda x, v, i=i: self.show_next_intermediate(i))
            if i == 0:
                self.layout.add_widget(w)
        self.layout.add_widget(self.dry_weight)
        self.layout.add_widget(self.loss)
        self.layout.add_widget(self.moisture_content)
        self.layout.add_widget(self.result)
        self.layout.add_widget(self.notes)
        self.layout.add_widget(Button(text="Submit", on_press=self.submit))
        self.layout.add_widget(Button(text="Back", on_press=self.go_back))
        self.layout.add_widget(Button(text="Home", on_press=self.go_home))
        self.wet_weight.bind(text=self.calculate)
        self.dry_weight.bind(text=self.calculate)

    def show_next_intermediate(self, index):
        if self.intermediate_weights[index].text and index < 7:
            if self.intermediate_weights[index + 1] not in self.layout.children:
                self.layout.add_widget(self.intermediate_weights[index + 1], index=4)

    def calculate(self, *args):
        try:
            wet = float(self.wet_weight.text)
            dry = float(self.dry_weight.text)
            loss = wet - dry
            self.loss.text = f"Loss: {loss:.2f} g"
            content = (loss / wet) * 100
            self.moisture_content.text = f"Moisture Content: {content:.2f}%"
            curve = json.load(open(CURVES_DIR / json.load(open(FORMS_DIR / self.form_id / "form.json"))['curve_name'] + ".json"))
            opt = curve["optimum_moisture"]
            lim = curve["moisture_limits"]
            self.result.text = f"Result: {'PASS' if opt + lim[0] <= content <= opt + lim[1] else 'FAIL'}"
        except (ValueError, TypeError):
            pass

    def submit(self, instance):
        if not all([self.station.text, self.feet_cl.text, self.wet_weight.text, self.dry_weight.text, self.test_method.text]):
            Popup(title="Error", content=Label(text="All required fields must be filled"), size_hint=(0.5, 0.3)).open()
            return
        test = {
            "type": "Moisture",
            "test_id": self.test_id,
            "station": self.station.text,
            "feet_cl": self.feet_cl.text,
            "depth": self.depth.text,
            "canister": self.canister.text,
            "test_method": self.test_method.text,
            "wet_weight": self.wet_weight.text,
            "intermediate_weights": [w.text for w in self.intermediate_weights if w.text],
            "dry_weight": self.dry_weight.text,
            "loss": self.loss.text,
            "moisture_content": self.moisture_content.text,
            "result": self.result.text.split(": ")[1],
            "notes": self.notes.text
        }
        form = json.load(open(FORMS_DIR / self.form_id / "form.json"))
        form['tests'].append(test)
        form['moisture_result'] = test['result']
        form['overall_result'] = "PASS" if all(t['result'] == "PASS" for t in form['tests']) else "FAIL"
        form['status'] = "Pending" if len(form['tests']) == 2 else "Incomplete"
        form['last_update'] = datetime.now().isoformat()
        with open(FORMS_DIR / self.form_id / "form.json", 'w') as f:
            json.dump(form, f)
        test_dir = FORMS_DIR / self.form_id / "Tests"
        test_dir.mkdir(exist_ok=True)
        with open(test_dir / f"{self.test_id}.json", 'w') as f:
            json.dump(test, f)
        for field in ["station", "feet_cl", "canister"]:
            save_recent_entry(field, getattr(self, field).text)
        self.manager.current = 'form'

# Admin Screen
class AdminScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        layout = BoxLayout(orientation='vertical')
        self.rv = RecycleView()
        self.rv.data = []
        layout.add_widget(TextInput(hint_text="Search", on_text=self.search))
        layout.add_widget(self.rv)
        layout.add_widget(Button(text="Add New Curve", on_press=self.go_add_curve))
        layout.add_widget(Button(text="Archive Curve", on_press=self.archive_curve))
        layout.add_widget(Button(text="Change Passcode", on_press=lambda x: self.manager.get_screen('home').show_passcode_popup('change_passcode')))
        layout.add_widget(Button(text="Home", on_press=self.go_home))
        self.add_widget(layout)
        self.load_curves()

    def go_add_curve(self, instance):
        self.manager.current = 'add_curve'

    def go_home(self, instance):
        self.manager.current = 'home'

    def load_curves(self):
        self.rv.data = [
            {"text": f"{c['name']} | {c['source']} | {c['sample_id']} | {c['ngi']}", "curve": c}
            for c in [json.load(open(f)) for f in CURVES_DIR.glob("*.json")]
        ]

    def archive_curve(self, instance):
        selected = [d['curve'] for d in self.rv.data if d.get('selected')]
        if not selected:
            return
        content = BoxLayout(orientation='vertical')
        content.add_widget(Label(text="Confirm Archive?"))
        content.add_widget(Button(text="Yes", on_press=lambda x: self.do_archive_curve(selected)))
        Popup(title="Archive Curve", content=content, size_hint=(0.5, 0.3)).open()

    def do_archive_curve(self, curves):
        for curve in curves:
            os.rename(CURVES_DIR / f"{curve['name']}.json", ARCHIVED_CURVES_DIR / f"{curve['name']}.json")
        self.load_curves()

# Add Curve Screen
class AddCurveScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        layout = BoxLayout(orientation='vertical', padding=10, spacing=10)
        self.name = TextInput(hint_text="Curve Name")
        self.soil_type = TextInput(hint_text="Soil Type")
        self.source = TextInput(hint_text="Source")
        self.sample_id = TextInput(hint_text="Sample ID")
        self.ngi = TextInput(hint_text="NGI")
        self.target_dtv = TextInput(hint_text="Target DTV")
        self.optimum_moisture = TextInput(hint_text="Optimum Moisture")
        self.moisture_limits = BoxLayout()
        self.moisture_limits.add_widget(TextInput(hint_text="Lower Limit"))
        self.moisture_limits.add_widget(TextInput(hint_text="Upper Limit"))
        self.notes = TextInput(hint_text="Notes")

# Archive Screen
class ArchiveScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        layout = BoxLayout(orientation='vertical')
        layout.add_widget(Button(text="Archived Curves", on_press=self.go_archived_curves))
        layout.add_widget(Button(text="Archived Forms", on_press=self.go_archived_forms))
        layout.add_widget(Button(text="Home", on_press=self.go_home))
        self.add_widget(layout)

    def go_archived_curves(self, instance):
        self.manager.current = 'archived_curves'

    def go_archived_forms(self, instance):
        self.manager.current = 'archived_forms'

    def go_home(self, instance):
        self.manager.current = 'home'

# Archived Curves Screen
class ArchivedCurvesScreen(CurvesScreen):
    def load_curves(self):
        self.rv.data = [
            {"text": f"{c['name']} | {c['source']} | {c['sample_id']} | {c['ngi']}", "curve": c}
            for c in [json.load(open(f)) for f in ARCHIVED_CURVES_DIR.glob("*.json")]
        ]

# Archived Forms Screen
class ArchivedFormsScreen(FormsScreen):
    def load_forms(self):
        forms = []
        for f in ARCHIVED_FORMS_DIR.glob("*.json"):
            form = json.load(open(f))
            forms.append({
                "text": f"{form['form_id']} | {form['status']} | {form['inspector_name']} | {form['date']}",
                "form": form,
                "color": "#FFFFFF"
            })
        forms.sort(key=lambda x: x["form"]["date"])
        self.rv.data = forms

    def create_form(self, instance=None):
        pass  # No creation in archive

    def archive_forms(self, instance):
        pass  # No archiving in archive

# PDF Generation
def generate_pdf(form_id):
    form = json.load(open(FORMS_DIR / form_id / "form.json"))
    curve = json.load(open(CURVES_DIR / f"{form['curve_name']}.json"))
    pdf_path = BASE_DIR / f"{form_id}.pdf"
    c = canvas.Canvas(str(pdf_path), pagesize=letter)
    c.drawString(100, 750, f"Form ID: {form['form_id']}")
    c.drawString(100, 730, f"Date: {form['date']}")
    c.drawString(100, 710, f"Inspector: {form['inspector_name']}")
    c.drawString(100, 690, f"Project #: {form['project_no']}")
    c.drawString(100, 670, f"Contract #: {form['contract_no']}")
    c.drawString(100, 650, f"Curve: {form['curve_name']}")
    y = 630
    for field in ["soil_type", "source", "sample_id", "ngi", "target_dtv", "optimum_moisture", "moisture_limits"]:
        c.drawString(100, y, f"{field.replace('_', ' ').title()}: {curve[field]}")
        y -= 20
    c.drawString(100, y, f"Moisture Result: {form['moisture_result']}")
    y -= 20
    c.drawString(100, y, f"Deflection Result: {form['deflection_result']}")
    y -= 20
    c.drawString(100, y, f"Overall Result: {form['overall_result']}")
    y -= 20
    c.drawString(100, y, f"Status: {form['status']}")
    y -= 20
    for test in form['tests']:
        c.drawString(100, y, f"Test: {test['test_id']} ({test['type']})")
        y -= 20
        for key, value in test.items():
            if key not in ['type', 'test_id']:
                c.drawString(120, y, f"{key.replace('_', ' ').title()}: {value}")
                y -= 20
    c.save()
    return pdf_path

# Run App
if platform.system() == "Emscripten":
    asyncio.ensure_future(FieldTestsApp().async_run())
else:
    if __name__ == "__main__":
        FieldTestsApp().run()
