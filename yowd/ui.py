"""Tkinter desktop interface for the local YOWD delivery prototype.

The interface only calls the public application service. Business decisions and
persistence stay in that service, so changing a screen cannot bypass validation.
"""

from __future__ import annotations

from datetime import date, datetime, time
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable

from .operating_hours import SUMMARY, next_operating_day


DATE_FORMAT = "%Y-%m-%d %H:%M"
EXPECTED_ERRORS = (ValueError, RuntimeError, OSError)


def _parse_datetime(value: str) -> datetime:
    try:
        return datetime.strptime(value.strip(), DATE_FORMAT)
    except ValueError as error:
        raise ValueError("Enter the date and time as YYYY-MM-DD HH:MM.") from error


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value.strip())
    except ValueError as error:
        raise ValueError("Enter the date as YYYY-MM-DD.") from error


def _next_shift(hour: int) -> str:
    """Default a new roster period to the next weekday, inside operating hours."""
    day = next_operating_day(datetime.now())
    return datetime.combine(day, time(hour)).strftime(DATE_FORMAT)


def _display(value: Any) -> str:
    return "" if value is None else str(value)


class FormDialog(tk.Toplevel):
    """Small editable form that remains open when validation fails."""

    def __init__(
        self,
        parent: tk.Misc,
        title: str,
        fields: list[tuple[str, str, str]],
        submit: Callable[[dict[str, str]], None],
        *,
        explanation: str = "",
        choices: dict[str, list[str]] | None = None,
        button_text: str = "Save",
    ) -> None:
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.resizable(True, False)
        self.choices = choices or {}
        self.variables: dict[str, tk.StringVar] = {}
        self.columnconfigure(0, weight=1)
        body = ttk.Frame(self, padding=20)
        body.grid(sticky="nsew")
        body.columnconfigure(1, weight=1)
        row = 0
        if explanation:
            ttk.Label(body, text=explanation, wraplength=490).grid(
                row=row, column=0, columnspan=2, sticky="w", pady=(0, 15)
            )
            row += 1
        first_widget: tk.Widget | None = None
        for key, label, initial in fields:
            ttk.Label(body, text=label).grid(
                row=row, column=0, sticky="w", padx=(0, 16), pady=6
            )
            variable = tk.StringVar(self, initial)
            self.variables[key] = variable
            if choices and key in choices:
                widget: tk.Widget = ttk.Combobox(
                    body,
                    textvariable=variable,
                    values=choices[key],
                    state="readonly",
                    width=45,
                )
            else:
                widget = ttk.Entry(body, textvariable=variable, width=45)
            widget.grid(row=row, column=1, sticky="ew", pady=6)
            if first_widget is None:
                first_widget = widget
            row += 1
        self.error = tk.StringVar(self)
        ttk.Label(
            body,
            textvariable=self.error,
            foreground="#a32121",
            wraplength=490,
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(10, 0))
        buttons = ttk.Frame(body)
        buttons.grid(row=row + 1, column=0, columnspan=2, sticky="e", pady=(15, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(
            side="left", padx=(0, 8)
        )

        def save() -> None:
            values = {key: variable.get().strip() for key, variable in self.variables.items()}
            try:
                submit(values)
            except EXPECTED_ERRORS as error:
                self.error.set(str(error))
                return
            self.destroy()

        ttk.Button(buttons, text=button_text, command=save).pack(side="left")
        self.bind("<Escape>", lambda _event: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.update_idletasks()
        self.minsize(550, self.winfo_reqheight())
        self.grab_set()
        if first_widget is not None:
            first_widget.focus_set()


class AvailabilityDialog(tk.Toplevel):
    """Edit one worker's periods locally, then save or cancel the whole draft."""

    def __init__(self, owner: "MainWindow", staff_id: str) -> None:
        super().__init__(owner.root)
        self.owner = owner
        self.staff_id = staff_id
        self.draft = list(owner.app.availability_periods(staff_id))
        worker = owner.staff_rows.get(staff_id, {})
        self.title(f"Availability for {worker.get('name', staff_id)}")
        self.transient(owner.root)
        self.resizable(True, True)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        body = ttk.Frame(self, padding=20)
        body.grid(sticky="nsew")
        body.columnconfigure(0, weight=1)
        ttk.Label(
            body,
            text=f"Operating hours: {SUMMARY}. Add, replace or remove periods in this draft. "
                 "Cancel leaves the saved schedule unchanged. Saving does not change jobs already allocated.",
            wraplength=560,
        ).grid(row=0, column=0, sticky="w", pady=(0, 12))
        self.periods = tk.Listbox(body, height=6, exportselection=False)
        self.periods.grid(row=1, column=0, sticky="ew")
        self.periods.bind("<<ListboxSelect>>", self._prefill)
        times = ttk.Frame(body)
        times.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        times.columnconfigure(1, weight=1)
        self.start_var = tk.StringVar(self)
        self.end_var = tk.StringVar(self)
        ttk.Label(times, text="From").grid(row=0, column=0, sticky="w", padx=(0, 12), pady=4)
        ttk.Entry(times, textvariable=self.start_var, width=24).grid(row=0, column=1, sticky="ew", pady=4)
        ttk.Label(times, text="Until").grid(row=1, column=0, sticky="w", padx=(0, 12), pady=4)
        ttk.Entry(times, textvariable=self.end_var, width=24).grid(row=1, column=1, sticky="ew", pady=4)
        draft_buttons = ttk.Frame(body)
        draft_buttons.grid(row=3, column=0, sticky="w", pady=(12, 0))
        for label, command in (
            ("Add period", self._add),
            ("Replace selected", self._replace),
            ("Remove selected", self._remove),
            ("Clear draft", self._clear),
        ):
            ttk.Button(draft_buttons, text=label, command=command).pack(side="left", padx=(0, 8))
        self.error = tk.StringVar(self)
        ttk.Label(body, textvariable=self.error, foreground="#a32121", wraplength=560).grid(
            row=4, column=0, sticky="w", pady=(12, 0),
        )
        actions = ttk.Frame(body)
        actions.grid(row=5, column=0, sticky="e", pady=(16, 0))
        ttk.Button(actions, text="Cancel", command=self.destroy).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="Save availability", command=self._save).pack(side="left")
        self.bind("<Escape>", lambda _event: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self._redraw()
        self.update_idletasks()
        self.minsize(620, self.winfo_reqheight())
        self.grab_set()

    def _redraw(self) -> None:
        self.periods.delete(0, "end")
        for start, end in self.draft:
            self.periods.insert("end", f"{start.strftime(DATE_FORMAT)} to {end.strftime(DATE_FORMAT)}")

    def _selected(self) -> int | None:
        selection = self.periods.curselection()
        if not selection:
            return None
        return int(selection[0])

    def _prefill(self, _event: tk.Event | None = None) -> None:
        index = self._selected()
        if index is None:
            return
        start, end = self.draft[index]
        self.start_var.set(start.strftime(DATE_FORMAT))
        self.end_var.set(end.strftime(DATE_FORMAT))

    def _typed_period(self) -> tuple[datetime, datetime]:
        return _parse_datetime(self.start_var.get()), _parse_datetime(self.end_var.get())

    def _apply(self, periods: list[tuple[datetime, datetime]]) -> None:
        try:
            self.draft = self.owner.app.merged_availability(periods)
        except EXPECTED_ERRORS as error:
            self.error.set(str(error))
            return
        self.error.set("")
        self._redraw()

    def _add(self) -> None:
        try:
            start, end = self._typed_period()
        except EXPECTED_ERRORS as error:
            self.error.set(str(error))
            return
        self._apply([*self.draft, (start, end)])

    def _replace(self) -> None:
        index = self._selected()
        if index is None:
            self.error.set("Select the period to replace.")
            return
        try:
            start, end = self._typed_period()
        except EXPECTED_ERRORS as error:
            self.error.set(str(error))
            return
        retained = [period for position, period in enumerate(self.draft) if position != index]
        self._apply([*retained, (start, end)])

    def _remove(self) -> None:
        index = self._selected()
        if index is None:
            self.error.set("Select the period to remove.")
            return
        self.draft = [period for position, period in enumerate(self.draft) if position != index]
        self.error.set("Period removed from the draft. Save to keep this change, or Cancel to restore the saved schedule.")
        self._redraw()

    def _clear(self) -> None:
        self.draft = []
        self.error.set("Draft cleared. Save to record no available hours, or Cancel to keep the saved schedule.")
        self._redraw()

    def _save(self) -> None:
        if not self.draft and not messagebox.askyesno(
            "Clear availability",
            "Save this worker with no available hours? Jobs already allocated stay assigned.",
            parent=self,
        ):
            self.error.set("Empty schedule was not saved.")
            return
        try:
            self.owner.app.set_availability(self.staff_id, self.draft)
        except EXPECTED_ERRORS as error:
            self.error.set(str(error))
            return
        self.owner.refresh()
        self.owner.status.set(f"Availability saved for {self.staff_id}.")
        self.destroy()


class NewRequestDialog(tk.Toplevel):
    """Collect a request and one or more parcels before saving anything."""

    PARCEL_FIELDS = (
        ("description", "Description"),
        ("weight_kg", "Weight (kg)"),
        ("length_cm", "Length (cm)"),
        ("width_cm", "Width (cm)"),
        ("height_cm", "Height (cm)"),
    )

    def __init__(self, owner: "MainWindow") -> None:
        super().__init__(owner.root)
        self.owner = owner
        self.title("New Delivery Request")
        self.transient(owner.root)
        self.geometry("880x760")
        self.minsize(780, 700)
        self.parcels: list[dict[str, str]] = []
        self.customer_variables: dict[str, tk.StringVar] = {}
        self.parcel_variables: dict[str, tk.StringVar] = {}
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        body = ttk.Frame(self, padding=16)
        body.grid(sticky="nsew")
        body.columnconfigure(1, weight=1)
        ttk.Label(body, text="Customer and Delivery", style="Section.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 12)
        )
        fields = (
            ("customer_name", "Customer name"),
            ("email", "Email"),
            ("phone", "Phone"),
            ("pickup_address", "Pickup street / delivery address"),
            ("pickup", "Pickup suburb"),
            ("destination_address", "Destination street / delivery address"),
            ("destination", "Destination suburb"),
        )
        for row, (key, label) in enumerate(fields, start=1):
            ttk.Label(body, text=label).grid(row=row, column=0, sticky="w", pady=3)
            variable = tk.StringVar(self)
            self.customer_variables[key] = variable
            ttk.Entry(body, textvariable=variable).grid(
                row=row, column=1, sticky="ew", pady=3, padx=(12, 0)
            )
        parcel_row = len(fields) + 1
        body.rowconfigure(parcel_row + 2, weight=1)
        ttk.Label(body, text="Parcels", style="Section.TLabel").grid(
            row=parcel_row, column=0, columnspan=2, sticky="w", pady=(14, 8)
        )
        editor = ttk.Frame(body)
        editor.grid(row=parcel_row + 1, column=0, columnspan=2, sticky="ew")
        for column, (key, label) in enumerate(self.PARCEL_FIELDS):
            editor.columnconfigure(column, weight=3 if column == 0 else 1)
            ttk.Label(editor, text=label).grid(
                row=0, column=column, sticky="w", padx=(0, 8)
            )
            variable = tk.StringVar(self)
            self.parcel_variables[key] = variable
            ttk.Entry(editor, textvariable=variable, width=10).grid(
                row=1, column=column, sticky="ew", padx=(0, 8), pady=(4, 8)
            )
        ttk.Button(editor, text="Add parcel", command=self._add_parcel).grid(
            row=1, column=5, pady=(4, 8)
        )
        list_frame = ttk.Frame(body)
        list_frame.grid(row=parcel_row + 2, column=0, columnspan=2, sticky="nsew")
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        self.parcel_tree = ttk.Treeview(
            list_frame,
            columns=("description", "weight", "dimensions"),
            show="headings",
            height=4,
            selectmode="browse",
        )
        self.parcel_tree.heading("description", text="Description")
        self.parcel_tree.heading("weight", text="Weight (kg)")
        self.parcel_tree.heading("dimensions", text="Dimensions (cm)")
        self.parcel_tree.column("description", width=330)
        self.parcel_tree.column("weight", width=100)
        self.parcel_tree.column("dimensions", width=190)
        self.parcel_tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.parcel_tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.parcel_tree.configure(yscrollcommand=scroll.set)
        parcel_actions = ttk.Frame(body)
        parcel_actions.grid(row=parcel_row + 3, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Button(parcel_actions, text="Edit selected parcel", command=self._edit_parcel).pack(
            side="left", padx=(0, 8)
        )
        ttk.Button(parcel_actions, text="Remove selected parcel", command=self._remove_parcel).pack(side="left")
        self.error = tk.StringVar(self)
        ttk.Label(body, textvariable=self.error, foreground="#a32121", wraplength=760).grid(
            row=parcel_row + 4, column=0, columnspan=2, sticky="w", pady=(10, 0)
        )
        ttk.Label(
            body,
            text="Sample service area: Melbourne, Richmond, Footscray, Hawthorn, Carlton, St Kilda, Brunswick, South Yarra, Docklands and Southbank. Enter the full delivery addresses separately from suburbs. Add each parcel before saving.",
            wraplength=760,
        ).grid(row=parcel_row + 5, column=0, columnspan=2, sticky="w", pady=(8, 0))
        buttons = ttk.Frame(body)
        buttons.grid(row=parcel_row + 6, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="left", padx=8)
        ttk.Button(buttons, text="Create request", command=self._save).pack(side="left")
        self.bind("<Escape>", lambda _event: self.destroy())
        self.grab_set()

    def _add_parcel(self) -> None:
        parcel = {key: value.get().strip() for key, value in self.parcel_variables.items()}
        if not all(parcel.values()):
            self.error.set("Enter all five parcel fields, then choose Add parcel.")
            return
        try:
            self.owner.app.validate_parcel(parcel)
        except EXPECTED_ERRORS as error:
            self.error.set(str(error))
            return
        self.parcels.append(parcel)
        self._redraw_parcels(len(self.parcels) - 1)
        for variable in self.parcel_variables.values():
            variable.set("")
        self.error.set("")

    def _redraw_parcels(self, selected_index: int | None = None) -> None:
        self.parcel_tree.delete(*self.parcel_tree.get_children())
        for index, parcel in enumerate(self.parcels):
            dimensions = " × ".join(parcel[key] for key in ("length_cm", "width_cm", "height_cm"))
            self.parcel_tree.insert(
                "", "end", iid=str(index),
                values=(parcel["description"], parcel["weight_kg"], dimensions),
            )
        if self.parcels and selected_index is not None:
            identifier = str(min(selected_index, len(self.parcels) - 1))
            self.parcel_tree.selection_set(identifier)
            self.parcel_tree.focus(identifier)
            self.parcel_tree.see(identifier)

    def _edit_parcel(self) -> None:
        selected = self.parcel_tree.selection()
        if not selected:
            self.error.set("Select a parcel from the list to edit it.")
            return
        index = int(selected[0])
        original = self.parcels[index]

        def save(values: dict[str, str]) -> None:
            self.owner.app.validate_parcel(values)
            self.parcels[index] = dict(values)
            self._redraw_parcels(index)
            self.error.set("")

        dialog = FormDialog(
            self, "Edit Parcel",
            [(key, label, original[key]) for key, label in self.PARCEL_FIELDS],
            save,
            explanation="Changes apply to this unsaved parcel only after validation. Cancel keeps its original values.",
            button_text="Save Parcel",
        )

        def restore_modal(event: tk.Event) -> None:
            if event.widget is dialog and self.winfo_exists():
                self.grab_set()

        dialog.bind("<Destroy>", restore_modal)

    def _remove_parcel(self) -> None:
        selected = self.parcel_tree.selection()
        if selected:
            index = int(selected[0])
            del self.parcels[index]
            self._redraw_parcels(index)
            self.error.set("")

    def _save(self) -> None:
        if any(variable.get().strip() for variable in self.parcel_variables.values()):
            self.error.set("A parcel is still in the input fields. Add it to the list or clear those fields.")
            return
        values = {key: variable.get().strip() for key, variable in self.customer_variables.items()}
        try:
            request_id = self.owner.app.create_request(**values, parcels=self.parcels)
        except EXPECTED_ERRORS as error:
            self.error.set(str(error))
            return
        self.owner.refresh(request_id=request_id)
        self.owner.status.set(f"Request {request_id} created.")
        self.destroy()


class MainWindow:
    """Main screen; accepts an existing root for a withdrawn-window smoke test."""

    def __init__(self, root: tk.Tk, app: Any) -> None:
        self.root = root
        self.app = app
        self.snapshot: dict[str, Any] = {}
        self.request_rows: dict[str, dict[str, Any]] = {}
        self.staff_rows: dict[str, dict[str, Any]] = {}
        root.title("YOWD | Delivery Management")
        root.geometry("1240x780")
        root.minsize(980, 680)
        style = ttk.Style(root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("TButton", padding=(10, 7))
        style.configure("Treeview", rowheight=30)
        style.configure("Treeview.Heading", padding=(8, 8))
        style.configure("Title.TLabel", font=("Segoe UI", 21, "bold"))
        style.configure("Section.TLabel", font=("Segoe UI", 11, "bold"))
        style.configure("Muted.TLabel", foreground="#52616f")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)
        header = ttk.Frame(root, padding=(20, 15, 20, 12))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="YOWD Delivery Management", style="Title.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            header,
            text="Local Prototype • Simulated Payment Records • Dates use Local Melbourne Time",
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Button(header, text="Load Sample Data", command=self._seed_demo).grid(
            row=0, column=1, padx=(12, 8)
        )
        ttk.Button(header, text="Refresh", command=self.refresh).grid(row=0, column=2)
        self.counts = tk.StringVar(root)
        ttk.Label(header, textvariable=self.counts, style="Muted.TLabel").grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(10, 0)
        )
        self.notebook = ttk.Notebook(root)
        self.notebook.grid(row=1, column=0, sticky="nsew", padx=20)
        self._build_requests()
        self._build_staff()
        self._build_statistics()
        footer = ttk.Frame(root, padding=(20, 10))
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        self.status = tk.StringVar(root, "Ready. Create a Request and Register Staff, or Load Sample Data.")
        ttk.Label(footer, textvariable=self.status, wraplength=1150).grid(sticky="w")
        self.storage = tk.StringVar(root)
        ttk.Label(footer, textvariable=self.storage, style="Muted.TLabel", wraplength=1150).grid(
            sticky="w", pady=(4, 0)
        )
        self.refresh()

    def _build_requests(self) -> None:
        tab = ttk.Frame(self.notebook, padding=14)
        self.notebook.add(tab, text="Delivery Requests")
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(2, weight=1)
        toolbar = ttk.Frame(tab)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        actions = (
            ("New Request", lambda: NewRequestDialog(self)),
            ("Edit Addresses", self._edit_addresses),
            ("Prepare Quote", self._quote),
            ("Accept Quote", lambda: self._respond(True)),
            ("Decline Quote", lambda: self._respond(False)),
            ("Allocate Worker", self._allocate),
            ("Record Pickup", self._pickup),
            ("Authorise Payment Exception", self._authorise),
            ("Delivered", lambda: self._delivery(True)),
            ("Failed Delivery", lambda: self._delivery(False)),
            ("Retry Pickup", self._retry_pickup),
        )
        for index, (label, callback) in enumerate(actions):
            ttk.Button(toolbar, text=label, command=callback).grid(
                row=index // 5, column=index % 5, sticky="ew", padx=(0, 6), pady=(0, 6)
            )
        for column in range(5):
            toolbar.columnconfigure(column, weight=1)
        ttk.Label(
            tab, text="Select a request to view its complete record or perform an action.",
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(0, 8))
        panes = ttk.Panedwindow(tab, orient="vertical")
        panes.grid(row=2, column=0, sticky="nsew")
        list_frame = ttk.Frame(panes)
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        columns = ("customer", "destination", "status", "quote_amount", "worker", "payment")
        self.request_tree = ttk.Treeview(
            list_frame, columns=columns, show="tree headings", selectmode="browse", height=8
        )
        self.request_tree.heading("#0", text="Request ID")
        self.request_tree.column("#0", width=130, minwidth=80)
        headings = ("Customer", "Destination", "Status", "Quote ($)", "Worker", "Payment")
        widths = (140, 180, 140, 85, 130, 130)
        for key, heading, width in zip(columns, headings, widths):
            self.request_tree.heading(key, text=heading)
            self.request_tree.column(key, width=width, minwidth=60)
        self.request_tree.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(list_frame, orient="vertical", command=self.request_tree.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(list_frame, orient="horizontal", command=self.request_tree.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.request_tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.request_tree.bind("<<TreeviewSelect>>", lambda _event: self._show_request())
        panes.add(list_frame, weight=3)
        details_frame = ttk.LabelFrame(panes, text="Selected request", padding=10)
        details_frame.columnconfigure(0, weight=1)
        details_frame.rowconfigure(0, weight=1)
        self.details = tk.Text(
            details_frame, wrap="word", height=10, state="disabled",
            font=("Consolas", 10), relief="flat", background="#fafbfc", padx=10, pady=8,
        )
        self.details.grid(row=0, column=0, sticky="nsew")
        details_scroll = ttk.Scrollbar(details_frame, orient="vertical", command=self.details.yview)
        details_scroll.grid(row=0, column=1, sticky="ns")
        self.details.configure(yscrollcommand=details_scroll.set)
        panes.add(details_frame, weight=2)

    def _build_staff(self) -> None:
        tab = ttk.Frame(self.notebook, padding=14)
        self.notebook.add(tab, text="Staff and Availability")
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(2, weight=1)
        toolbar = ttk.Frame(tab)
        toolbar.grid(row=0, column=0, sticky="w", pady=(0, 12))
        for label, callback in (
            ("Register Staff", self._register_staff),
            ("Set availability", self._availability),
            ("Deactivate selected staff", self._deactivate),
        ):
            ttk.Button(toolbar, text=label, command=callback).pack(side="left", padx=(0, 8))
        ttk.Label(
            tab,
            text=f"Operating hours: {SUMMARY}. Former workers remain visible so delivery history is retained. "
                 "Availability periods use YYYY-MM-DD HH:MM.",
            wraplength=1050, style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(0, 12))
        list_frame = ttk.Frame(tab)
        list_frame.grid(row=2, column=0, sticky="nsew")
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        self.staff_tree = ttk.Treeview(
            list_frame, columns=("name", "active", "availability"),
            show="tree headings", selectmode="browse",
        )
        self.staff_tree.heading("#0", text="Staff ID")
        self.staff_tree.heading("name", text="Name")
        self.staff_tree.heading("active", text="Employment")
        self.staff_tree.heading("availability", text="Availability")
        self.staff_tree.column("#0", width=150)
        self.staff_tree.column("name", width=200)
        self.staff_tree.column("active", width=110)
        self.staff_tree.column("availability", width=550)
        self.staff_tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.staff_tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.staff_tree.configure(yscrollcommand=scroll.set)

    def _build_statistics(self) -> None:
        tab = ttk.Frame(self.notebook, padding=18)
        self.notebook.add(tab, text="Delivery Statistics")
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(2, weight=1)
        ttk.Label(tab, text="Delivery outcomes by completion period", style="Section.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 12)
        )
        filters = ttk.Frame(tab)
        filters.grid(row=1, column=0, sticky="w", pady=(0, 12))
        today = date.today()
        self.statistics_start = tk.StringVar(self.root, today.replace(day=1).isoformat())
        self.statistics_end = tk.StringVar(self.root, today.isoformat())
        ttk.Label(filters, text="From (YYYY-MM-DD)").pack(side="left", padx=(0, 8))
        ttk.Entry(filters, textvariable=self.statistics_start, width=14).pack(side="left", padx=(0, 18))
        ttk.Label(filters, text="To (inclusive)").pack(side="left", padx=(0, 8))
        ttk.Entry(filters, textvariable=self.statistics_end, width=14).pack(side="left", padx=(0, 18))
        ttk.Button(filters, text="Calculate", command=self._statistics).pack(side="left")
        self.statistics_text = tk.Text(
            tab, wrap="word", state="disabled", font=("Consolas", 11),
            background="#fafbfc", relief="flat", padx=15, pady=15,
        )
        self.statistics_text.grid(row=2, column=0, sticky="nsew")
        self._set_text(self.statistics_text, "Select a reporting period and choose Calculate.")

    @staticmethod
    def _set_text(widget: tk.Text, value: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.configure(state="disabled")

    def refresh(self, request_id: str | None = None) -> None:
        selected_request = request_id or self._selected_request(required=False)
        selected_staff = self._selected_staff(required=False)
        try:
            snapshot = self.app.overview()
        except EXPECTED_ERRORS as error:
            messagebox.showerror("Unable to load records", str(error), parent=self.root)
            return
        self.snapshot = snapshot
        self.request_rows = {str(row["id"]): row for row in snapshot.get("requests", [])}
        self.staff_rows = {str(row["id"]): row for row in snapshot.get("staff", [])}
        self.request_tree.delete(*self.request_tree.get_children())
        for identifier, row in self.request_rows.items():
            self.request_tree.insert(
                "", "end", iid=identifier, text=identifier,
                values=tuple(_display(row.get(key)) for key in self.request_tree["columns"]),
            )
        self.staff_tree.delete(*self.staff_tree.get_children())
        for identifier, row in self.staff_rows.items():
            availability = row.get("availability", "")
            if isinstance(availability, list):
                availability = "; ".join(map(str, availability))
            self.staff_tree.insert(
                "", "end", iid=identifier, text=identifier,
                values=(row.get("name", ""), "Active" if row.get("active") else "Former / inactive", availability),
            )
        if selected_request in self.request_rows:
            self.request_tree.selection_set(selected_request)
            self.request_tree.see(selected_request)
        if selected_staff in self.staff_rows:
            self.staff_tree.selection_set(selected_staff)
        active_staff = sum(bool(row.get("active")) for row in self.staff_rows.values())
        counts = snapshot.get("counts", {})
        count_text = " | ".join(f"{key}: {value}" for key, value in counts.items())
        self.counts.set(
            f"{len(self.request_rows)} requests  •  {active_staff} active workers"
            + (f"  •  {count_text}" if count_text else "")
        )
        self.storage.set("Local data: " + _display(snapshot.get("storage_path", "")))
        self._show_request()

    def _selected_request(self, required: bool = True) -> str | None:
        selection = self.request_tree.selection()
        if selection:
            return selection[0]
        if required:
            messagebox.showinfo("Select a request", "Select a delivery request first.", parent=self.root)
        return None

    def _selected_staff(self, required: bool = True) -> str | None:
        selection = self.staff_tree.selection()
        if selection:
            return selection[0]
        if required:
            messagebox.showinfo("Select staff", "Select a staff member first.", parent=self.root)
        return None

    def _show_request(self) -> None:
        request_id = self._selected_request(required=False)
        if request_id is None:
            self._set_text(self.details, "No request selected. Use New request to start a delivery transaction.")
            return
        try:
            content = self.app.request_details(request_id)
        except EXPECTED_ERRORS as error:
            content = str(error)
        self._set_text(self.details, content)

    def _action(self, action: Callable[[], Any], success: str) -> None:
        try:
            result = action()
        except EXPECTED_ERRORS as error:
            messagebox.showerror("Action could not be completed", str(error), parent=self.root)
            return
        self.refresh()
        self.status.set(success + (f" {result}" if result is not None else ""))

    def _worker_choices(self) -> dict[str, str]:
        return {
            f"{row.get('name', '')} | {identifier}"
            + (" (inactive)" if not row.get("active") else ""): identifier
            for identifier, row in self.staff_rows.items()
        }

    def _worker_form(
        self, title: str, explanation: str, submit: Callable[[str, dict[str, str]], None],
        fields: list[tuple[str, str, str]] | None = None, *, button_text: str = "Save",
    ) -> None:
        choices = self._worker_choices()
        if not choices:
            messagebox.showinfo("No staff registered", "Register a staff member first.", parent=self.root)
            return

        def save(values: dict[str, str]) -> None:
            if values["staff"] not in choices:
                raise ValueError("Choose the worker reporting or performing this action.")
            submit(choices[values["staff"]], values)
            self.refresh()

        FormDialog(
            self.root, title, [("staff", "Worker", "")] + (fields or []), save,
            explanation=explanation, choices={"staff": list(choices)}, button_text=button_text,
        )
    def _quote(self) -> None:
        request_id = self._selected_request()
        if request_id is None:
            return
        suggestion = ""
        try:
            pickup_at, delivery_at = self.app.suggest_quote_window(request_id)
            pickup_default = pickup_at.strftime(DATE_FORMAT)
            delivery_default = delivery_at.strftime(DATE_FORMAT)
        except EXPECTED_ERRORS as error:
            pickup_default = ""
            delivery_default = ""
            suggestion = f"No suggested window: {error} "
        # Show How the Sample Tariff Worked Out the Amount
        try:
            _, breakdown = self.app.quote_estimate(request_id)
            tariff_note = f"Sample Tariff: {breakdown}. "
        # If Tarif Could Not be Calculated
        except EXPECTED_ERRORS as error:
            tariff_note = f"No Tariff Estimate: {error} "

        def save(values: dict[str, str]) -> None:
            amount = self.app.prepare_quote(
                request_id, _parse_datetime(values["pickup"]), _parse_datetime(values["delivery"])
            )
            self.refresh()
            self.status.set(f"Quote prepared for {request_id}: ${amount}. Customer response is still required.")

        FormDialog(
            self.root, "Prepare delivery quote",
            [("pickup", "Estimated pickup", pickup_default), ("delivery", "Estimated delivery", delivery_default)],
            save,
            explanation=suggestion + "Suggested times consider request age, duration and current availability; they do not reserve a worker. Times are editable. Enter YYYY-MM-DD HH:MM.\n\n"
                        + tariff_note + "The quoted amount is calculated by the application.",
            button_text="Prepare Quote",
        )

    def _edit_addresses(self) -> None:
        request_id = self._selected_request()
        if request_id is None:
            return
        row = self.request_rows[request_id]

        def save(values: dict[str, str]) -> None:
            self.app.update_request_addresses(
                request_id, values["pickup_address"], values["destination_address"]
            )
            self.refresh()
            self.status.set(f"Delivery addresses corrected for {request_id}; service suburbs retained.")

        FormDialog(
            self.root, "Edit delivery addresses",
            [("pickup_address", "Pickup street / delivery address", _display(row.get("pickup_address"))),
             ("destination_address", "Destination street / delivery address", _display(row.get("destination_address")))],
            save,
            explanation=f"Service suburbs: {row.get('pickup', '')} to {row.get('destination', '')}. "
                        "Addresses can be corrected only while the request is Requested, before quotation. "
                        "Blank fields indicate an address has not been recorded.",
            button_text="Save addresses",
        )

    def _respond(self, accepted: bool) -> None:
        request_id = self._selected_request()
        if request_id is None:
            return
        response = "accept" if accepted else "decline"
        if not messagebox.askyesno(
            "Confirm customer response", f"Record the customer's decision to {response} the current quote?",
            parent=self.root,
        ):
            return
        self._action(
            lambda: self.app.respond_quote(request_id, accepted),
            f"Customer decision recorded: quote {'accepted' if accepted else 'declined'}.",
        )

    def _allocate(self) -> None:
        request_id = self._selected_request()
        if request_id is None:
            return
        try:
            report = self.app.allocation_options(request_id)
        except EXPECTED_ERRORS as error:
            messagebox.showerror("Action could not be completed", str(error), parent=self.root)
            return
        if not report["options"]:
            messagebox.showinfo("No staff registered", "Register a staff member first.", parent=self.root)
            return
        labels = {
            f"{option['name']} | {option['id']} — "
            f"{'Eligible' if option['eligible'] else option['reason']}": option["id"]
            for option in report["options"]
        }

        def save(values: dict[str, str]) -> None:
            if values["staff"] not in labels:
                raise ValueError("Choose a worker.")
            self.app.allocate(request_id, labels[values["staff"]])
            self.refresh()
            self.status.set(f"Worker allocated to {request_id}.")

        FormDialog(
            self.root, "Allocate delivery worker",
            [("staff", "Worker", "")], save,
            explanation=(
                f"Operating hours: {report['operating_hours']}. {report['window_text']} "
                "A quote does not reserve a worker, and another job in the same window does not "
                "block allocation. Eligible workers can take this request. Any other row explains the refusal."
            ),
            choices={"staff": list(labels)},
            button_text="Allocate",
        )

    def _pickup(self) -> None:
        request_id = self._selected_request()
        if request_id is None:
            return
        row = self.request_rows.get(request_id, {})
        recorded_amount = row.get("received_amount")
        amount_default = recorded_amount if recorded_amount not in (None, "") else row.get("quote_amount")
        # Reason Drop Down for Failure Selection
        failures = {
            f"Failed: {reason}": reason
            for reason in ("Customer not present", "Parcel missing", "Parcel damaged", "Parcel does not match request")
        }
        # Return Drop Down List of All Parcel Names and Their ID
        parcels = {
            f"{description} | {parcel_id}": parcel_id 
            for parcel_id, description in self.app.request_parcels(request_id)
        }

        def save(worker_id: str, values: dict[str, str]) -> None:
            collected = values["parcels"] == "All parcels collected and checked"
            if not messagebox.askyesno(
                "Confirm pickup outcome",
                "Record successful parcel collection and the simulated payment outcome?"
                if collected else "Record a failed pickup? No payment is recorded and the assignment will end.",
                parent=self.root,
            ):
                raise ValueError("Pickup was not recorded. You can correct the form or choose Cancel.")
            outcome = self.app.pickup(
                request_id, worker_id, values["amount"], parcel_ok=collected,
                failure=failures.get(values["parcels"]), parcel_id=parcels.get(values["parcel"]),
            )
            self.status.set(f"Pickup outcome for {request_id}: {outcome}")

        choices = self._worker_choices()
        if not choices:
            messagebox.showinfo("No staff registered", "Register and allocate a worker first.", parent=self.root)
            return

        def submit(values: dict[str, str]) -> None:
            if values["staff"] not in choices:
                raise ValueError("Choose the worker reporting the pickup.")
            if not values["parcels"]:
                raise ValueError("Choose the parcel collection outcome.")
            save(choices[values["staff"]], values)
            self.refresh()

        FormDialog(
            self.root, "Record pickup and simulated payment",
            [("staff", "Reporting Worker", ""), ("parcels", "Parcel Outcome", ""), ("parcel", "Affected Parcel", ""), ("amount", "Amount Received ($)", _display(amount_default))],
            submit,
            explanation="Payment is recorded locally; no bank transaction occurs. A payment mismatch requires a separate office authorisation before pickup can complete.",
            choices={"staff": list(choices), "parcels": ["All parcels collected and checked", *failures], "parcel": list(parcels)},
            button_text="Record Pickup",
        )

    def _authorise(self) -> None:
        request_id = self._selected_request()
        if request_id is None:
            return

        def save(values: dict[str, str]) -> None:
            self.app.authorise_payment(request_id, values["authorised_by"], values["reason"])
            self.refresh()
            self.status.set(
                "Authorisation recorded. The allocated worker must confirm pickup again using the recorded received amount."
            )

        FormDialog(
            self.root, "Office action: authorise payment exception",
            [("authorised_by", "Authorised by", ""), ("reason", "Business reason", "")],
            save,
            explanation="Use this distinct office action only after a payment exception has been recorded. "
                        "Enter the person authorising the exception and their reason.",
            button_text="Record Authorisation",
        )

    def _delivery(self, successful: bool) -> None:
        request_id = self._selected_request()
        if request_id is None:
            return

        def save(worker_id: str, values: dict[str, str]) -> None:
            if not successful and not values["reason"]:
                raise ValueError("Enter the reason delivery failed.")
            if not messagebox.askyesno(
                "Confirm final delivery outcome",
                "Confirm all parcels have been handed over successfully?"
                if successful else "Record failed delivery, end this assignment and retain the pickup payment?",
                parent=self.root,
            ):
                raise ValueError("Delivery outcome was not recorded. Correct the form or choose Cancel.")
            outcome = self.app.deliver(
                request_id, worker_id, successful, values.get("reason", "")
            )
            self.status.set(f"Delivery outcome for {request_id}: {outcome}")

        self._worker_form(
            "Record delivered parcels" if successful else "Record failed delivery",
            "The application checks that the reporting worker owns the active assignment and pickup is complete.",
            save, [] if successful else [("reason", "Failure reason", "")],
            button_text="Record Delivered" if successful else "Record Failed Delivery",
        )

    def _retry_pickup(self) -> None:
        request_id = self._selected_request()
        if request_id is None:
            return
        if messagebox.askyesno(
            "Office action: allow pickup retry",
            "Return this failed-pickup request to Accepted for a new allocation? The previous assignment remains in its history.", parent=self.root,
        ):
            self._action(lambda: self.app.retry_pickup(request_id), "Pickup retry authorised; request awaits allocation.")

    def _register_staff(self) -> None:
        def save(values: dict[str, str]) -> None:
            staff_id = self.app.register_staff(
                values["name"], values["email"], values["phone"],
                _parse_datetime(values["start"]), _parse_datetime(values["end"]),
            )
            self.refresh()
            self.status.set(f"Staff member {staff_id} registered.")

        FormDialog(
            self.root, "Register delivery staff",
            [("name", "Name", ""), ("email", "Email", ""), ("phone", "Phone", ""),
             ("start", "Available from", _next_shift(8)), ("end", "Available until", _next_shift(18))],
            save,
            explanation=f"Register a worker with one period inside {SUMMARY}. Dates: YYYY-MM-DD HH:MM.",
            button_text="Register staff",
        )

    def _availability(self) -> None:
        staff_id = self._selected_staff()
        if staff_id is None:
            return
        AvailabilityDialog(self, staff_id)

    def _deactivate(self) -> None:
        staff_id = self._selected_staff()
        if staff_id is None:
            return
        name = self.staff_rows.get(staff_id, {}).get("name", staff_id)
        if messagebox.askyesno(
            "Deactivate staff", f"Deactivate {name}? Their record and delivery history will be retained.",
            parent=self.root,
        ):
            self._action(lambda: self.app.deactivate_staff(staff_id), f"{name} deactivated.")

    def _statistics(self) -> None:
        try:
            start = _parse_date(self.statistics_start.get())
            end = _parse_date(self.statistics_end.get())
            result = self.app.statistics(start, end)
        except EXPECTED_ERRORS as error:
            messagebox.showerror("Invalid reporting period", str(error), parent=self.root)
            return
        lines = [
            f"Reporting period: {start.isoformat()} to {end.isoformat()} (inclusive)", "",
            f"Completed deliveries: {result.get('completed', 0)}",
            f"Failed outcomes: {result.get('failed', 0)}",
        ]
        average = result.get("average_minutes")
        if average is not None:
            lines.append(f"Average completion time (minutes): {average}")
        lines.extend(["", "Completed deliveries by worker:"])
        by_staff = result.get("by_staff", {})
        if isinstance(by_staff, dict):
            lines.extend(f"  {worker}: {count}" for worker, count in by_staff.items())
        else:
            lines.append(str(by_staff))
        if not by_staff:
            lines.append("  No completed deliveries in this period.")
        self._set_text(self.statistics_text, "\n".join(lines))
        self.status.set("Statistics calculated from retained delivery outcomes.")

    def _seed_demo(self) -> None:
        if messagebox.askyesno(
            "Load Sample Data",
            "Load clearly labelled sample customers, requests and staff into this local database? This is allowed only when the database is empty.", parent=self.root,
        ):
            self._action(self.app.seed_demo, "Sample data loaded. These records are for demonstration.")


def launch(app: Any) -> None:
    """Launch the desktop interface and close the application on exit."""
    root = tk.Tk()
    MainWindow(root, app)

    def close() -> None:
        app.close()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close)
    root.mainloop()
