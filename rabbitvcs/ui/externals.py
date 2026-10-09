"""Structured svn:externals editor, with the original text always accessible."""

from gi.repository import Gtk

from rabbitvcs import gettext
from rabbitvcs.util.externals import External, ExternalsDocument, resolve_url, revision

_ = gettext.gettext


def show_error(parent, message):
    dialog = Gtk.MessageDialog(
        transient_for=parent, modal=True, message_type=Gtk.MessageType.ERROR,
        buttons=Gtk.ButtonsType.CLOSE, text=str(message),
    )
    dialog.run()
    dialog.destroy()


class ExternalDialog(Gtk.Dialog):
    def __init__(self, parent, path, item=None):
        super().__init__(title=_("Edit External"), transient_for=parent, modal=True)
        self.path = path
        self.log_window = None
        self.add_buttons(_("Cancel"), Gtk.ResponseType.CANCEL, _("OK"), Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.OK)
        self.set_default_size(640, -1)
        grid = Gtk.Grid(column_spacing=12, row_spacing=10, margin=16)
        self.get_content_area().add(grid)
        item = item or External("", "")
        self.fields = {}
        for row, (key, label, value) in enumerate([
            ("local_path", _("Local path:"), item.local_path),
            ("url", _("URL:"), item.url),
            ("peg", _("Peg revision:"), item.peg),
            ("operative", _("Operative revision:"), item.operative),
        ]):
            entry = Gtk.Entry(text=value, hexpand=True, activates_default=True)
            grid.attach(Gtk.Label(label=label, xalign=0), 0, row, 1, 1)
            grid.attach(entry, 1, row, 1, 1)
            self.fields[key] = entry
        self.fields["peg"].set_placeholder_text(_("HEAD (default)"))
        self.fields["operative"].set_placeholder_text(_("Same as Peg (default)"))
        self.fields["peg"].set_tooltip_text(_("Identifies the external at this revision. Show log fills this field."))
        self.fields["operative"].set_tooltip_text(_("Revision to check out. Leave empty to use the Peg revision."))
        head = Gtk.Button(label=_("Use HEAD"))
        head.connect("clicked", self.use_head)
        grid.attach(head, 2, 2, 1, 1)
        button = Gtk.Button(label=_("Show log"))
        button.set_sensitive(bool(path))
        button.connect("clicked", self.show_log)
        grid.attach(button, 2, 3, 1, 1)
        self.show_all()

    def use_head(self, *args):
        self.fields["peg"].set_text("")
        self.fields["operative"].set_text("")

    def select_revision(self, value):
        if value != "":
            self.fields["peg"].set_text(str(value))

    def show_log(self, *args):
        from rabbitvcs.vcs import VCS
        from rabbitvcs.ui.log import ExternalLogDialog

        try:
            url = self.fields["url"].get_text().strip()
            if not url:
                raise ValueError(_("Enter the external URL first."))
            peg = revision(self.fields["peg"].get_text())
            svn = VCS().svn()
            absolute = resolve_url(url, str(svn.get_repo_url(self.path)),
                                   str(svn.get_repo_root_url(self.path)))
            peg_revision = svn.revision("number", number=int(peg)) if peg and peg != "HEAD" else svn.revision("head")
            self.log_window = ExternalLogDialog(absolute, self.select_revision, peg_revision)
            window = self.log_window.get_widget("Log")
            window.set_transient_for(self)
            window.set_modal(True)
            window.set_destroy_with_parent(True)
            self.log_window.show()
        except Exception as exc:
            show_error(self, exc)

    def run(self):
        try:
            while super().run() == Gtk.ResponseType.OK:
                try:
                    item = External(**{key: field.get_text().strip() for key, field in self.fields.items()})
                    item.serialize()
                    return item
                except ValueError as exc:
                    show_error(self, exc)
            return None
        finally:
            if self.log_window is not None:
                self.log_window.on_cancel_clicked(None)
            self.destroy()


class ExternalsEditor(Gtk.Box):
    def __init__(self, path, value):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.path = path
        self.document = ExternalsDocument(value)
        self.raw = Gtk.CheckButton(label=_("Edit raw svn:externals text"))
        self.pack_start(self.raw, False, False, 0)
        self.stack = Gtk.Stack()
        self.pack_start(self.stack, True, True, 0)
        structured = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.model = Gtk.ListStore(int, str, str, str, str)
        self.tree = Gtk.TreeView(model=self.model)
        for index, title in enumerate([_("Local path"), _("URL"), _("Peg"), _("Operative")], 1):
            renderer = Gtk.CellRendererText()
            column = Gtk.TreeViewColumn(title, renderer, text=index)
            column.set_resizable(True)
            self.tree.append_column(column)
        self.tree.connect("row-activated", self.edit)
        scroll = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        scroll.set_min_content_height(210)
        scroll.add(self.tree)
        structured.pack_start(scroll, True, True, 0)
        buttons = Gtk.Box(spacing=8)
        for label, callback in [(_("Add"), self.add), (_("Edit"), self.edit), (_("Remove"), self.remove)]:
            button = Gtk.Button(label=label)
            button.connect("clicked", callback)
            buttons.pack_start(button, False, False, 0)
        structured.pack_start(buttons, False, False, 0)
        self.warning = Gtk.Label(xalign=0, wrap=True)
        structured.pack_start(self.warning, False, False, 0)
        self.stack.add_named(structured, "structured")
        self.textview = Gtk.TextView(monospace=True)
        textscroll = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        textscroll.add(self.textview)
        self.stack.add_named(textscroll, "raw")
        self.raw.connect("toggled", self.toggle_raw)
        self.refresh()
        self.show_all()

    def refresh(self):
        self.model.clear()
        errors = False
        for index, item, error in self.document.entries():
            if item:
                self.model.append([index, item.local_path, item.url, item.peg or "HEAD", item.operative or item.peg or "HEAD"])
            else:
                self.model.append([index, _("Unrecognised line"), self.document.lines[index].rstrip(), "", ""])
                errors = True
        self.warning.set_text(_("Some lines cannot be edited as fields. They are preserved; use the raw text editor to change them.") if errors else "")

    def toggle_raw(self, *args):
        if self.raw.get_active():
            self.textview.get_buffer().set_text(self.document.text())
            self.stack.set_visible_child_name("raw")
        else:
            self.document = ExternalsDocument(self.get_text())
            self.refresh()
            self.stack.set_visible_child_name("structured")

    def get_text(self):
        if self.stack.get_visible_child_name() == "raw":
            buffer = self.textview.get_buffer()
            return buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)
        return self.document.text()

    def selected_index(self):
        model, iterator = self.tree.get_selection().get_selected()
        return model[iterator][0] if iterator is not None else None

    def add(self, *args):
        item = ExternalDialog(self.get_toplevel(), self.path).run()
        if item:
            self.document.append(item)
            self.refresh()

    def edit(self, *args):
        index = self.selected_index()
        if index is None:
            return
        item = next(item for i, item, error in self.document.entries() if i == index)
        if item is None:
            self.raw.set_active(True)
            return
        changed = ExternalDialog(self.get_toplevel(), self.path, item).run()
        if changed and changed != item:
            self.document.replace(index, changed)
            self.refresh()

    def remove(self, *args):
        index = self.selected_index()
        if index is not None:
            del self.document.lines[index]
            self.refresh()
