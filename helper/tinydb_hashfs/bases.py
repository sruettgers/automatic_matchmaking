import datetime as dt
import json
import os
from io import BufferedReader, FileIO
from pathlib import Path
from typing import Tuple

from hashfs import HashFS
from tinydb import TinyDB
from tinydb_serialization import Serializer, SerializationMiddleware

import sacred.optional as opt

# Set data type values for abstract properties in Serializers
series_type = opt.pandas.Series if opt.has_pandas else None
dataframe_type = opt.pandas.DataFrame if opt.has_pandas else None
ndarray_type = opt.np.ndarray if opt.has_numpy else None


# class ArchivableFilepath:
#     def __init__(self, path: str):
#         self.path = path
#
#     def __copy__(self):
#         return ArchivableFilepath(self.path)
#
#     def __deepcopy__(self, memo):
#         return ArchivableFilepath(self.path)
#
#     def __repr__(self):
#         return f"ArchivableFilepath({self.path})"
#
#     def __str__(self):
#         return repr(self)


class BufferedReaderWrapper(BufferedReader):
    """Custom wrapper to allow for copying of file handle.

    tinydb_serialisation currently does a deepcopy on all the content of the
    dictionary before serialisation. By default, file handles are not
    copiable so this wrapper is necessary to create a duplicate of the
    file handle passes in.

    Note that the file passed in will therefor remain open as the copy is the
    one that gets closed.
    """

    def __init__(self, f_obj):
        f_obj = FileIO(f_obj.name)
        super().__init__(f_obj)

    def __copy__(self):
        return self
        # f = open(self.name, self.mode)
        # return BufferedReaderWrapper(f)

    def __deepcopy__(self, memo):
        return self
        # f = open(self.name, self.mode)
        # return BufferedReaderWrapper(f)


class DateTimeSerializer(Serializer):
    OBJ_CLASS = dt.datetime  # The class this serializer handles

    def encode(self, obj):
        return obj.strftime("%Y-%m-%dT%H:%M:%S.%f")

    def decode(self, s):
        return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.%f")


class NdArraySerializer(Serializer):
    OBJ_CLASS = ndarray_type

    def encode(self, obj):
        return json.dumps(obj.tolist(), check_circular=True)

    def decode(self, s):
        return opt.np.array(json.loads(s))


class DataFrameSerializer(Serializer):
    OBJ_CLASS = dataframe_type

    def encode(self, obj):
        return obj.to_json()

    def decode(self, s):
        return opt.pandas.read_json(s)


class SeriesSerializer(Serializer):
    OBJ_CLASS = series_type

    def encode(self, obj):
        return obj.to_json()

    def decode(self, s):
        return opt.pandas.read_json(s, typ="series")


class FileSerializer(Serializer):
    OBJ_CLASS = BufferedReaderWrapper

    def __init__(self, fs):
        self.fs = fs

    def encode(self, obj):
        address = self.fs.put(obj)
        return json.dumps(address.id)

    def decode(self, s):
        id_ = json.loads(s)
        file_reader = self.fs.open(id_)
        file_reader = BufferedReaderWrapper(file_reader)
        file_reader.hash = id_
        return file_reader


class MockFileSerializer(Serializer):
    OBJ_CLASS = BufferedReaderWrapper

    def __init__(self):
        pass

    def encode(self, obj):
        return "BufferedReaderWrapper"

    def decode(self, s):
        return s


# class ArchivableFileSerializer(Serializer):
#     OBJ_CLASS = ArchivableFilepath
#
#     def __init__(self, fs: HashFS):
#         self.fs = fs
#
#     def encode(self, obj: ArchivableFilepath):
#         print("encode", repr(obj.path))
#         address = self.fs.put(Path(obj.path))
#         return json.dumps(address.id)
#
#     def decode(self, s):
#         id_ = json.loads(s)
#         address = self.fs.get(id_)
#         return ArchivableFilepath(address.relpath)


def get_db_file_manager(
    root_dir, get_all_databases
) -> Tuple[TinyDB, HashFS] | Tuple[dict[str, TinyDB], HashFS]:
    root_dir = Path(root_dir)
    fs = HashFS(root_dir / "hashfs", depth=3, width=2, algorithm="md5")

    def get_serialization_store():
        # Setup Serialisation object for non list/dict objects
        serialization_store = SerializationMiddleware()
        serialization_store.register_serializer(DateTimeSerializer(), "TinyDate")
        # serialization_store.register_serializer(FileSerializer(fs), "TinyFile")
        serialization_store.register_serializer(MockFileSerializer(), "TinyFile")
        # serialization_store.register_serializer(ArchivableFileSerializer(fs), "TinyArchivableFilepath")

        if opt.has_numpy:
            serialization_store.register_serializer(NdArraySerializer(), "TinyArray")
        if opt.has_pandas:
            serialization_store.register_serializer(
                DataFrameSerializer(), "TinyDataFrame"
            )
            serialization_store.register_serializer(SeriesSerializer(), "TinySeries")

        return serialization_store

    import socket
    import pathlib

    load_db = lambda filename: TinyDB(
        os.path.join(root_dir, filename), storage=get_serialization_store()
    )  #

    if not get_all_databases:
        print("[TinyDBObserver] Opening db", f"{socket.gethostname()}.json")
        db = load_db(f"{socket.gethostname()}.json")
        return db, fs

    database_paths = list(pathlib.Path(root_dir).glob("*.json"))

    return {db.stem: load_db(db.name) for db in database_paths}, fs
