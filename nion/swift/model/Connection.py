"""
    Contains classes related to connections between library objects.
"""

from __future__ import annotations

# standard libraries
import copy
import functools
import typing

# third party libraries
# None

# local libraries
from nion.swift.model import Graphics
from nion.swift.model import Persistence
from nion.utils import Binding

if typing.TYPE_CHECKING:
    from nion.swift.model import DisplayItem
    from nion.swift.model import Project
    from nion.utils import Event


class Connection(Persistence.PersistentObject):
    """ Represents a connection between two objects. """

    def __init__(self, type: str, *, parent: typing.Optional[Persistence.PersistentObject] = None) -> None:
        super().__init__()
        self.define_type(type)
        self.define_property("parent_specifier", changed=self.__parent_specifier_changed, key="parent_uuid")
        self.__parent_reference = self.create_item_reference(item=parent)
        self.parent_specifier = parent.project.create_specifier(parent).write() if parent else None

    @property
    def project(self) -> Project.Project:
        return typing.cast("Project.Project", self.container)

    def create_proxy(self) -> Persistence.PersistentObjectProxy:
        return self.project.create_item_proxy(item=self)

    @property
    def item_specifier(self) -> Persistence.PersistentObjectSpecifier:
        return Persistence.PersistentObjectSpecifier(item_uuid=self.uuid)

    def clone(self) -> Connection:
        connection = copy.deepcopy(self)
        connection.uuid = self.uuid
        return connection

    def _property_changed(self, name: str, value: typing.Any) -> None:
        self.notify_property_changed(name)

    @property
    def parent(self) -> typing.Optional[Persistence.PersistentObject]:
        return self.__parent_reference.item

    @parent.setter
    def parent(self, parent: typing.Optional[Persistence.PersistentObject]) -> None:
        self.__parent_reference.item = parent
        self.parent_specifier = parent.project.create_specifier(parent).write() if parent else None

    def __parent_specifier_changed(self, name: str, d: typing.Dict[str, typing.Any]) -> None:
        self.__parent_reference.item_specifier = Persistence.PersistentObjectSpecifier.read(d)


class PropertyConnection(Connection):
    """ Binds the properties of two objects together. """

    def __init__(self, source: typing.Optional[Persistence.PersistentObject] = None,
                 source_property: typing.Optional[str] = None,
                 target: typing.Optional[Persistence.PersistentObject] = None,
                 target_property: typing.Optional[str] = None, *,
                 parent: typing.Optional[Persistence.PersistentObject] = None) -> None:
        super().__init__("property-connection", parent=parent)
        self.define_property("source_specifier", source.project.create_specifier(source).write() if source else None, changed=self.__source_specifier_changed, key="source_uuid")
        self.define_property("source_property")
        self.define_property("target_specifier", target.project.create_specifier(target).write() if target else None, changed=self.__target_specifier_changed, key="target_uuid")
        self.define_property("target_property")
        # these are only set in persistent object context changed
        self.__binding: typing.Optional[Binding.Binding] = None
        self.__target_property_changed_listener: typing.Optional[Event.EventListener] = None
        self.__source_reference = self.create_item_reference(item=source)
        self.__target_reference = self.create_item_reference(item=target)
        # suppress messages while we're setting source or target
        self.__suppress = False
        # set up the proxies

        def configure_binding() -> None:
            if self._source and self._target:
                assert not self.__binding
                self.__binding = Binding.PropertyBinding(self._source, self.source_property)
                self.__binding.target_setter = self.__set_target_from_source
                # while reading, the data item in the display data channel will not be connected;
                # we still set its value here. when the data item becomes valid, it will update.
                self.__binding.update_target_direct(self.__binding.get_target_value())

        def release_binding() -> None:
            if self.__binding:
                self.__binding.close()
                self.__binding = None
            if self.__target_property_changed_listener:
                self.__target_property_changed_listener.close()
                self.__target_property_changed_listener = None

        self.__source_reference.on_item_registered = lambda x: configure_binding()
        self.__source_reference.on_item_unregistered = lambda x: release_binding()

        def configure_target() -> None:
            def property_changed(target: typing.Optional[Persistence.PersistentObject], property_name: str) -> None:
                if property_name == self.target_property:
                    self.__set_source_from_target(getattr(target, property_name))

            assert self.__target_property_changed_listener is None
            if self._target:
                self.__target_property_changed_listener = self._target.property_changed_event.listen(functools.partial(property_changed, self._target))
            configure_binding()

        self.__target_reference.on_item_registered = lambda x: configure_target()
        self.__target_reference.on_item_unregistered = lambda x: release_binding()

        # but set up if we were passed objects
        if source is not None:
            self.__source_reference.item = source
        if source_property:
            self.source_property = source_property
        if target is not None:
            self.__target_reference.item = target
        if target_property:
            self.target_property = target_property

        if self._target:
            configure_target()

    def close(self) -> None:
        if self.__binding:
            self.__binding.close()
            self.__binding = None
        if self.__target_property_changed_listener:
            self.__target_property_changed_listener.close()
            self.__target_property_changed_listener = None
        super().close()

    @property
    def connected_items(self) -> typing.List[typing.Optional[Persistence.PersistentObject]]:
        return [self._source, self._target]

    @property
    def _source(self) -> typing.Optional[Persistence.PersistentObject]:
        return self.__source_reference.item

    @property
    def _target(self) -> typing.Optional[Persistence.PersistentObject]:
        return self.__target_reference.item

    def __source_specifier_changed(self, name: str, d: typing.Dict[str, typing.Any]) -> None:
        self.__source_reference.item_specifier = Persistence.PersistentObjectSpecifier.read(d)

    def __target_specifier_changed(self, name: str, d: typing.Dict[str, typing.Any]) -> None:
        self.__target_reference.item_specifier = Persistence.PersistentObjectSpecifier.read(d)

    def __set_target_from_source(self, value: typing.Any) -> None:
        assert not self._closed
        if not self.__suppress:
            self.__suppress = True
            setattr(self._target, self.target_property, value)
            self.__suppress = False

    def __set_source_from_target(self, value: typing.Any) -> None:
        assert not self._closed
        if not self.__suppress:
            self.__suppress = True
            if self.__binding:
                self.__binding.update_source(value)
            self.__suppress = False


class IntervalListConnection(Connection):
    """Binds the intervals on a display to the interval_descriptors on a line profile graphic.

    This is a one way connection from the display to the line profile graphic.
    """

    def __init__(self, display_item: typing.Optional[DisplayItem.DisplayItem] = None,
                 line_profile: typing.Optional[Graphics.LineProfileGraphic] = None, *,
                 parent: typing.Optional[Persistence.PersistentObject] = None) -> None:
        super().__init__("interval-list-connection", parent=parent)
        self.define_property("source_specifier", display_item.project.create_specifier(display_item).write() if display_item else None, changed=self.__source_specifier_changed, key="source_uuid")
        self.define_property("target_specifier", line_profile.project.create_specifier(line_profile).write() if line_profile and line_profile.project else None, changed=self.__target_specifier_changed, key="target_uuid")
        # these are only set in persistent object context changed
        self.__item_inserted_event_listener: typing.Optional[Event.EventListener] = None
        self.__item_removed_event_listener: typing.Optional[Event.EventListener] = None
        self.__interval_mutated_listeners: typing.List[Event.EventListener] = list()
        self.__source_reference = self.create_item_reference(item=display_item)
        self.__target_reference = self.create_item_reference(item=line_profile)

        def detach() -> None:
            for listener in self.__interval_mutated_listeners:
                listener.close()
            self.__interval_mutated_listeners = list()

        def reattach() -> None:
            detach()
            interval_descriptors = list()
            if self._source:
                for region in self._source.graphics:
                    if isinstance(region, Graphics.IntervalGraphic):
                        interval_descriptor = {"interval": region.interval, "color": "#F00"}
                        interval_descriptors.append(interval_descriptor)
                        self.__interval_mutated_listeners.append(region.property_changed_event.listen(lambda k: reattach()))
            if self._target:
                if self._target.interval_descriptors != interval_descriptors:
                    self._target.interval_descriptors = interval_descriptors

        def item_inserted(key: str, value: typing.Any, before_index: int) -> None:
            if key == "graphics" and self._target:
                reattach()

        def item_removed(key: str, value: typing.Any, index: int) -> None:
            if key == "graphics" and self._target:
                reattach()

        def source_registered(source: Persistence.PersistentObject) -> None:
            if self._source:
                self.__item_inserted_event_listener = self._source.item_inserted_event.listen(item_inserted)
                self.__item_removed_event_listener = self._source.item_removed_event.listen(item_removed)
            reattach()

        def target_registered(target: Persistence.PersistentObject) -> None:
            reattach()

        def unregistered(item: Persistence.PersistentObject) -> None:
            if self.__item_inserted_event_listener:
                self.__item_inserted_event_listener.close()
                self.__item_inserted_event_listener = None
            if self.__item_removed_event_listener:
                self.__item_removed_event_listener.close()
                self.__item_removed_event_listener = None

        self.__source_reference.on_item_registered = source_registered
        self.__source_reference.on_item_unregistered = unregistered

        self.__target_reference.on_item_registered = target_registered
        self.__target_reference.on_item_unregistered = unregistered

        # but setup if we were passed objects
        if display_item is not None:
            self.__source_reference.item = display_item
            source_registered(display_item)
        if line_profile is not None:
            self.__target_reference.item = line_profile
            target_registered(line_profile)

    @property
    def connected_items(self) -> typing.List[typing.Optional[Persistence.PersistentObject]]:
        return [self._source, self._target]

    @property
    def _source(self) -> typing.Optional[Persistence.PersistentObject]:
        return self.__source_reference.item

    @property
    def _target(self) -> typing.Optional[Persistence.PersistentObject]:
        return self.__target_reference.item

    def __source_specifier_changed(self, name: str, d: typing.Dict[str, typing.Any]) -> None:
        self.__source_reference.item_specifier = Persistence.PersistentObjectSpecifier.read(d)

    def __target_specifier_changed(self, name: str, d: typing.Dict[str, typing.Any]) -> None:
        self.__target_reference.item_specifier = Persistence.PersistentObjectSpecifier.read(d)


def connection_factory(lookup_id: typing.Callable[[str], str]) -> typing.Optional[Persistence.PersistentObject]:
    build_map = {
        "property-connection": PropertyConnection,
        "interval-list-connection": IntervalListConnection,
    }
    type = lookup_id("type")
    return build_map[type]() if type in build_map else None
