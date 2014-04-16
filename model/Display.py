"""
    Contains classes related to display of data items.
"""

# standard libraries
import gettext
import weakref

# third party libraries
# None

# local libraries
from nion.swift.model import DataItem
from nion.swift.model import Storage

_ = gettext.gettext


class Display(Storage.StorageBase):
    # Displays are associated with exactly one data item.

    def __init__(self):
        super(Display, self).__init__()
        self.storage_properties += ["properties"]
        self.storage_relationships += ["graphics"]
        self.storage_type = "display"
        # these are handled manually for now.
        # self.register_dependent_key("data_range", "display_range")
        # self.register_dependent_key("display_limits", "display_range")
        self.__weak_data_item = None
        self.__properties = dict()
        self.__graphics = Storage.MutableRelationship(self, "graphics")
        self.__drawn_graphics = Model.ListModel(self, "drawn_graphics")
        self.__preview = None
        self.__shared_thread_pool = ThreadPool.create_thread_queue()
        self.__processors = dict()
        self.__processors["thumbnail"] = DataItem.ThumbnailDataItemProcessor(self)
        self.__processors["histogram"] = DataItem.HistogramDataItemProcessor(self)

    def about_to_delete(self):
        self.__shared_thread_pool.close()
        for graphic in copy.copy(self.graphics):
            self.remove_graphic(graphic)
        self._set_data_item(None)

    @classmethod
    def build(cls, datastore, item_node, uuid_):
        properties = datastore.get_property(item_node, "properties")
        graphics = datastore.get_items(item_node, "graphics")
        display = cls()
        display.__properties = properties if properties else dict()
        display.extend_graphics(graphics)
        return display

    def __deepcopy__(self, memo):
        display_copy = DataItem()
        with display_copy.property_changes() as property_accessor:
            property_accessor.properties.clear()
            property_accessor.properties.update(self.properties)
        for graphic in self.graphics:
            display_copy.append_graphic(copy.deepcopy(graphic, memo))
        memo[id(self)] = display_copy
        return display_copy

    def add_shared_task(self, task_id, item, fn):
        self.__shared_thread_pool.add_task(task_id, item, fn)

    def get_processor(self, processor_id):
        return self.__processors[processor_id]

    def __get_data_item(self):
        return self.__weak_data_item() if self.__weak_data_item else None
    data_item = property(__get_data_item)

    # called from data item when added/removed.
    def _set_data_item(self, data_item):
        if self.data_item:
            self.data_item.remove_observer(self)
            self.data_item.remove_listener(self)
            self.data_item.remove_ref()
        self.__weak_data_item = weakref.ref(data_item) if data_item else None
        if self.data_item:
            self.data_item.add_ref()
            self.data_item.add_observer(self)
            self.data_item.add_listener(self)

    def __get_properties(self):
        return self.__properties.copy()
    properties = property(__get_properties)

    def __grab_properties(self):
        return self.__properties
    def __release_properties(self):
        self.notify_set_property("properties", self.__properties)
        self.notify_listeners("display_changed", self)
        self.__preview = None

    def property_changes(self):
        grab_properties = DataItem.__grab_properties
        release_properties = DataItem.__release_properties
        class PropertyChangeContextManager(object):
            def __init__(self, data_item):
                self.__data_item = data_item
            def __enter__(self):
                return self
            def __exit__(self, type, value, traceback):
                release_properties(self.__data_item)
            def __get_properties(self):
                return grab_properties(self.__data_item)
            properties = property(__get_properties)
        return PropertyChangeContextManager(self)

    def __get_preview_2d(self):
        if self.__preview is None:
            with self.data_item.data_ref() as data_ref:
                data = data_ref.data
            if Image.is_data_2d(data):
                data_2d = Image.scalar_from_array(data)
            # TODO: fix me 3d
            elif Image.is_data_3d(data):
                data_2d = Image.scalar_from_array(data.reshape(tuple([data.shape[0] * data.shape[1], ] + list(data.shape[2::]))))
            else:
                data_2d = None
            if data_2d is not None:
                data_range = self.data_range
                display_limits = self.display_limits
                self.__preview = Image.create_rgba_image_from_array(data_2d, data_range=data_range, display_limits=display_limits)
        return self.__preview
    preview_2d = property(__get_preview_2d)

    def get_processed_data(self, processor_id, ui, completion_fn):
        return self.get_processor(processor_id).get_data(ui, completion_fn)

    def __get_drawn_graphics(self):
        return self.__drawn_graphics
    drawn_graphics = property(__get_drawn_graphics)

    def __get_display_calibrated_values(self):
        return self.__properties.get("display_calibrated_values", True)
    def __set_display_calibrated_values(self, display_calibrated_values):
        with self.property_changes() as pc:
            pc.properties["display_calibrated_values"] = display_calibrated_values
        self.notify_set_property("display_calibrated_values", display_calibrated_values)
    display_calibrated_values = property(__get_display_calibrated_values, __set_display_calibrated_values)

    def __get_display_limits(self):
        return self.__properties.get("display_limits", True)
    def __set_display_limits(self, display_limits):
        with self.property_changes() as pc:
            pc.properties["display_limits"] = display_limits
        self.notify_set_property("display_limits", display_limits)
        self.notify_set_property("display_range", self.display_range)
    display_limits = property(__get_display_limits, __set_display_limits)

    def __get_data_range(self):
        return self.data_item.data_range
    data_range = property(__get_data_range)

    def __get_display_range(self):
        data_range = self.data_range
        return self.display_limits if self.display_limits else data_range
    # TODO: this is only valid after data has been called (!)
    display_range = property(__get_display_range)

    # message sent from data item. established using add/remove observer.
    def property_changed(self, sender, property, value):
        if property == "data_range":
            self.__preview = None
            self.notify_set_property(property, value)
            self.notify_set_property("display_range", self.display_range)

    def notify_insert_item(self, key, value, before_index):
        super(Display, self).notify_insert_item(key, value, before_index)
        if key == "graphics":
            self.__drawn_graphics.insert(before_index, value)
            value.add_listener(self)
            self.notify_listeners("display_changed", self)

    def notify_remove_item(self, key, value, index):
        super(Display, self).notify_remove_item(key, value, index)
        if key == "graphics":
            del self.__drawn_graphics[index]
            value.remove_listener(self)
            self.notify_listeners("display_changed", self)

    # this message received from data item. the connection is established using
    # add_listener and remove_listener.
    def data_item_content_changed(self, data_item, changes):
        self.__preview = None
        self.notify_listeners("display_changed", self)
        # clear the processor caches
        for processor in self.__processors.values():
            processor.data_item_changed()

    # this is called from the data item when an operation is inserted into one of
    # its child data items. this method updates the drawn graphics list.
    def operation_inserted_into_child_data_item(self, child_data_item, child_operation_item):
        # first count the graphics intrinsic to this object.
        index = len(self.graphics)
        # now cycle through each data item.
        for data_item in self.data_item.data_items:
            # and each operation within that data item.
            for operation_item in data_item.operations:
                operation_graphics = operation_item.graphics
                # if this is the match operation, do the insert
                if data_item == child_data_item and operation_item == child_operation_item:
                    for operation_graphic in reversed(operation_graphics):
                        operation_graphic.add_listener(self)
                        self.__drawn_graphics.insert(index, operation_graphic)
                        return  # done
                # otherwise count up the graphics and continue
                index += len(operation_graphics)

    def operation_removed_from_child_data_item(self, operation_item):
        # removal is easier since we don't need an insert point
        for operation_graphic in operation_item.graphics:
            operation_graphic.remove_listener(self)
            self.__drawn_graphics.remove(operation_graphic)

    def __get_graphics(self):
        """ A copy of the graphics """
        return copy.copy(self.__graphics)
    graphics = property(__get_graphics)

    def insert_graphic(self, index, graphic):
        """ Insert a graphic before the index """
        self.__graphics.insert(index, graphic)

    def append_graphic(self, graphic):
        """ Append a graphic """
        self.__graphics.append(graphic)

    def remove_graphic(self, graphic):
        """ Remove a graphic """
        self.__graphics.remove(graphic)

    def extend_graphics(self, graphics):
        """ Extend the graphics array with the list of graphics """
        self.__graphics.extend(graphics)

    # drawn graphics and the regular graphic items, plus those derived from the operation classes
    def __get_drawn_graphics(self):
        """ List of drawn graphics """
        return self.__drawn_graphics
    drawn_graphics = property(__get_drawn_graphics)

    def remove_drawn_graphic(self, drawn_graphic):
        """ Remove a drawn graphic which might be intrinsic or a graphic associated with an operation on a child """
        if drawn_graphic in self.__graphics:
            self.__graphics.remove(drawn_graphic)
        else:  # a synthesized graphic
            # cycle through each data item.
            for data_item in self.data_items:
                # and each operation within that data item.
                for operation_item in data_item.operations:
                    operation_graphics = operation_item.graphics
                    if drawn_graphic in operation_graphics:
                        self.data_items.remove(data_item)

    # this message comes from the graphic. the connection is established when a graphic
    # is added or removed from this object.
    def graphic_changed(self, graphic):
        self.notify_listeners("display_changed", self)

    # override from storage to watch for changes to this data item. notify observers.
    def notify_set_property(self, key, value):
        super(Display, self).notify_set_property(key, value)
        for processor in self.__processors.values():
            processor.item_property_changed(key, value)
