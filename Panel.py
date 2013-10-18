# standard libraries
import code
import gettext
import logging
import os
import sys
import uuid
import weakref
from contextlib import contextmanager
from StringIO import StringIO

# third party libraries
# None

# local libraries
# None


_ = gettext.gettext


class Panel(object):
    """
        The Panel represents a panel within the document window.

        The Panel includes the ability to load a Qt widget. The Qt widget will be
        deleted when the Panel is deleted.
        """

    def __init__(self, document_controller, panel_id, display_name):
        self.__document_controller_weakref = weakref.ref(document_controller)
        self.ui = document_controller.ui
        self.panel_id = panel_id
        self.dock_widget = None
        self.display_name = display_name

    # subclasses can override to clean up when the panel closes.
    def close(self):
        pass

    def __get_document_controller(self):
        return self.__document_controller_weakref()
    document_controller = property(__get_document_controller)

    def __str__(self):
        return self.display_name

    # access for the property. this allows C++ to get the value.
    def get_uuid_str(self):
        return str(self.uuid)


class OutputPanel(Panel):
    def __init__(self, document_controller, panel_id, properties):
        super(OutputPanel, self).__init__(document_controller, panel_id, "Output")
        properties["min-height"] = 180
        self.widget = self.ui.create_output_widget(properties)
        output_widget = self.widget  # no access to OutputPanel.self inside OutputPanelHandler
        class OutputPanelHandler(logging.Handler):
            def __init__(self, ui):
                super(OutputPanelHandler, self).__init__()
                self.ui = ui
            def emit(self, record):
                if record.levelno >= logging.INFO:
                    output_widget.send(record.getMessage())
        self.__output_panel_handler = OutputPanelHandler(document_controller.ui)
        logging.getLogger().addHandler(self.__output_panel_handler)
    def close(self):
        logging.getLogger().removeHandler(self.__output_panel_handler)
        super(OutputPanel, self).close()


@contextmanager
def reassign_stdout(new_stdout, new_stderr):
    oldstdout, oldtsderr = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = new_stdout, new_stderr
    yield
    sys.stdout, sys.stderr = oldstdout, oldtsderr


class ConsolePanel(Panel):
    # TODO: Replace this with a proper console. As it is, basic functionality
    # like raw_input is broken, pdb doesn't work and we can't embed an IPython
    # console.
    def __init__(self, document_controller, panel_id, properties):
        super(ConsolePanel, self).__init__(document_controller, panel_id, "Console")
        properties["min-height"] = 180
        self.widget = self.ui.create_console_widget(properties)
        self.widget.on_interpret_command = lambda command: self.interpret_command(command)
        self.other_stdout = StringIO()
        self.other_stderr = StringIO()
        # sys.ps1/2 is not always defined, we'll use it if it is
        self.ps1 = getattr(sys, "ps1", ">>> ")
        self.ps2 = getattr(sys, "ps2", "... ")

        locals = {'__name__': None, '__console__': None, '__doc__': None, '_document_controller': document_controller}
        self.console = code.InteractiveConsole(locals)
        lines = [
            "from nion.swift import DocumentController, DocumentModel, DataItem, Image",
            "import logging",
            "import numpy as np",
            "import numpy as numpy",
            "_data = DocumentModel.DocumentModel.DataAccessor(_document_controller.document_model)",
            "_data_item = DocumentModel.DocumentModel.DataItemAccessor(_document_controller.document_model)",
            "_document_model = _document_controller.document_model",
            # deprecated abbreviations
            "_d = _data",
            "_di = _data_item",
            "dc = _document_controller",
            ]
        for l in lines:
            self.interpret_command(l)

    # interpretCommand is called from the intrinsic widget.
    def interpret_command(self, command):
        with reassign_stdout(self.other_stdout, self.other_stderr):
            incomplete = self.console.push(command)

        prompt = self.ps2 if incomplete else self.ps1
        if self.other_stderr.getvalue():
            result =  self.other_stderr.getvalue()
            error_code = -1
        else:
            result =  self.other_stdout.getvalue()
            error_code = 0
        self.other_stdout.truncate(0)
        self.other_stderr.truncate(0)
        return result, error_code, prompt


class HeaderWidgetController(object):

    def __init__(self, ui, title=None):
        self.ui = ui
        self.__title = title if title else ""
        header_height = 20 if sys.platform == "win32" else 22
        self.canvas_widget = self.ui.create_canvas_widget(properties={"height": header_height})
        self.__layer = self.canvas_widget.create_layer()
        self.canvas_widget.on_size_changed = lambda width, height: self.__header_size_changed(width, height)
        self.__update_header()

    def __str__(self):
        return self.__title

    def __get_title(self):
        return self.__title
    def __set_title(self, title):
        if self.__title != title:
            self.__title = title
            self.__update_header()
    title = property(__get_title, __set_title)

    def __update_header(self):

        canvas = self.canvas_widget

        ctx = self.__layer.drawing_context

        ctx.clear()

        ctx.save()
        ctx.begin_path()
        ctx.move_to(0, 0)
        ctx.line_to(0, canvas.height)
        ctx.line_to(canvas.width, canvas.height)
        ctx.line_to(canvas.width, 0)
        ctx.close_path()
        gradient = ctx.create_linear_gradient(0, 0, 0, canvas.height);
        gradient.add_color_stop(0, '#ededed');
        gradient.add_color_stop(1, '#cacaca');
        ctx.fill_style = gradient
        ctx.fill()
        ctx.restore()

        ctx.save()
        ctx.begin_path()
        # line is adjust 1/2 pixel down to align to pixel boundary
        ctx.move_to(0, 0.5)
        ctx.line_to(canvas.width, 0.5)
        ctx.stroke_style = '#FFF'
        ctx.stroke()
        ctx.restore()

        ctx.save()
        ctx.begin_path()
        # line is adjust 1/2 pixel down to align to pixel boundary
        ctx.move_to(0, canvas.height-0.5)
        ctx.line_to(canvas.width, canvas.height-0.5)
        ctx.stroke_style = '#b0b0b0'
        ctx.stroke()
        ctx.restore()

        ctx.save()
        ctx.font = 'normal 11px serif'
        ctx.text_align = 'center'
        ctx.text_baseline = 'middle'
        ctx.fill_style = '#000'
        ctx.fill_text(self.title, canvas.width/2, canvas.height/2+1)
        ctx.restore()

        canvas.draw()

    def __header_size_changed(self, width, height):
        if width > 0 and height > 0:
            self.__update_header()
