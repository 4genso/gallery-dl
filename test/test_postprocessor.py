#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright 2019 Mike Fährmann
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as
# published by the Free Software Foundation.

import os.path
import zipfile
import tempfile
from datetime import datetime

import unittest
from unittest.mock import Mock, mock_open, patch

from gallery_dl import postprocessor, extractor, util, config
from gallery_dl.postprocessor.common import PostProcessor


class MockPostprocessorModule(Mock):
    __postprocessor__ = "mock"


class TestPostprocessorModule(unittest.TestCase):

    def setUp(self):
        postprocessor._cache.clear()

    def test_find(self):
        for name in (postprocessor.modules):
            cls = postprocessor.find(name)
            self.assertEqual(cls.__name__, name.capitalize() + "PP")
            self.assertIs(cls.__base__, PostProcessor)

        self.assertEqual(postprocessor.find("foo"), None)
        self.assertEqual(postprocessor.find(1234) , None)
        self.assertEqual(postprocessor.find(None) , None)

    @patch("importlib.import_module")
    def test_cache(self, import_module):
        import_module.return_value = MockPostprocessorModule()

        for name in (postprocessor.modules):
            postprocessor.find(name)
        self.assertEqual(import_module.call_count, len(postprocessor.modules))

        # no new calls to import_module
        for name in (postprocessor.modules):
            postprocessor.find(name)
        self.assertEqual(import_module.call_count, len(postprocessor.modules))


class BasePostprocessorTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.extractor = extractor.find("test:")
        cls.dir = tempfile.TemporaryDirectory()
        cls.fnum = 0
        config.set(("base-directory",), cls.dir.name)

    @classmethod
    def tearDownClass(cls):
        cls.dir.cleanup()
        config.clear()

    def _create(self, options=None, data=None):
        kwdict = {"category": "test", "filename": "file", "extension": "ext"}
        if options is None:
            options = {}
        if data is not None:
            kwdict.update(data)

        self.pathfmt = util.PathFormat(self.extractor)
        self.pathfmt.set_directory(kwdict)
        self.pathfmt.set_filename(kwdict)

        pp = postprocessor.find(self.__class__.__name__[:-4].lower())
        return pp(self.pathfmt, options)


class ClassifyTest(BasePostprocessorTest):

    def test_classify_default(self):
        pp = self._create()

        self.assertEqual(pp.mapping, {
            ext: directory
            for directory, exts in pp.DEFAULT_MAPPING.items()
            for ext in exts
        })
        self.pathfmt.set_extension("jpg")

        pp.prepare(self.pathfmt)
        path = os.path.join(self.dir.name, "test", "Pictures")
        self.assertEqual(pp._dir, path)
        self.assertEqual(self.pathfmt.realpath, path + "/file.jpg")

        with patch("os.makedirs") as mkdirs:
            pp.run(self.pathfmt)
            mkdirs.assert_called_once_with(path, exist_ok=True)

    def test_classify_noop(self):
        pp = self._create()
        rp = self.pathfmt.realpath

        pp.prepare(self.pathfmt)
        self.assertEqual(pp._dir, None)
        self.assertEqual(self.pathfmt.realpath, rp)

        with patch("os.makedirs") as mkdirs:
            pp.run(self.pathfmt)
            self.assertEqual(mkdirs.call_count, 0)

    def test_classify_custom(self):
        pp = self._create({"mapping": {
            "foo/bar": ["foo", "bar"],
        }})

        self.assertEqual(pp.mapping, {
            "foo": "foo/bar",
            "bar": "foo/bar",
        })
        self.pathfmt.set_extension("foo")

        pp.prepare(self.pathfmt)
        path = os.path.join(self.dir.name, "test", "foo", "bar")
        self.assertEqual(pp._dir, path)
        self.assertEqual(self.pathfmt.realpath, path + "/file.foo")

        with patch("os.makedirs") as mkdirs:
            pp.run(self.pathfmt)
            mkdirs.assert_called_once_with(path, exist_ok=True)


class MetadataTest(BasePostprocessorTest):

    def test_metadata_default(self):
        pp = self._create()

        # default arguments
        self.assertEqual(pp.write    , pp._write_json)
        self.assertEqual(pp.ascii    , False)
        self.assertEqual(pp.indent   , 4)
        self.assertEqual(pp.extension, "json")

    def test_metadata_json(self):
        pp = self._create({
            "mode"     : "json",
            "ascii"    : True,
            "indent"   : 2,
            "extension": "JSON",
        })

        self.assertEqual(pp.write    , pp._write_json)
        self.assertEqual(pp.ascii    , True)
        self.assertEqual(pp.indent   , 2)
        self.assertEqual(pp.extension, "JSON")

        with patch("builtins.open", mock_open()) as m:
            pp.prepare(self.pathfmt)
            pp.run(self.pathfmt)

        path = self.pathfmt.realpath + ".JSON"
        m.assert_called_once_with(path, "w", encoding="utf-8")
        self.assertEqual(self._output(m), """{
  "category": "test",
  "extension": "ext",
  "filename": "file"
}
""")

    def test_metadata_tags(self):
        pp = self._create({"mode": "tags"}, {"tags": ["foo", "bar", "baz"]})
        self.assertEqual(pp.write, pp._write_tags)
        self.assertEqual(pp.extension, "txt")

        with patch("builtins.open", mock_open()) as m:
            pp.prepare(self.pathfmt)
            pp.run(self.pathfmt)

        path = self.pathfmt.realpath + ".txt"
        m.assert_called_once_with(path, "w", encoding="utf-8")
        self.assertEqual(self._output(m), "foo\nbar\nbaz\n")

    def test_metadata_tags_split_1(self):
        pp = self._create({"mode": "tags"}, {"tags": "foo, bar, baz"})
        with patch("builtins.open", mock_open()) as m:
            pp.prepare(self.pathfmt)
            pp.run(self.pathfmt)
        self.assertEqual(self._output(m), "foo\nbar\nbaz\n")

    def test_metadata_tags_split_2(self):
        pp = self._create(
            {"mode": "tags"},
            {"tags": "foobar1 foobar2 foobarbaz"},
        )
        with patch("builtins.open", mock_open()) as m:
            pp.prepare(self.pathfmt)
            pp.run(self.pathfmt)
        self.assertEqual(self._output(m), "foobar1\nfoobar2\nfoobarbaz\n")

    def test_metadata_tags_tagstring(self):
        pp = self._create({"mode": "tags"}, {"tag_string": "foo, bar, baz"})
        with patch("builtins.open", mock_open()) as m:
            pp.prepare(self.pathfmt)
            pp.run(self.pathfmt)
        self.assertEqual(self._output(m), "foo\nbar\nbaz\n")

    def test_metadata_custom(self):
        pp = self._create(
            {"mode": "custom", "format": "{foo}\n{missing}\n"},
            {"foo": "bar"},
        )
        self.assertEqual(pp.write, pp._write_custom)
        self.assertEqual(pp.extension, "txt")
        self.assertTrue(pp.formatter)

        with patch("builtins.open", mock_open()) as m:
            pp.prepare(self.pathfmt)
            pp.run(self.pathfmt)
        self.assertEqual(self._output(m), "bar\nNone\n")

    @staticmethod
    def _output(mock):
        return "".join(
            call[1][0]
            for call in mock.mock_calls
            if call[0] == "().write"
        )


class MtimeTest(BasePostprocessorTest):

    def test_mtime_default(self):
        pp = self._create()
        self.assertEqual(pp.key, "date")

    def test_mtime_datetime(self):
        pp = self._create(None, {"date": datetime(1980, 1, 1)})
        pp.prepare(self.pathfmt)
        pp.run(self.pathfmt)
        self.assertEqual(self.pathfmt.kwdict["_mtime"], 315529200)

    def test_mtime_timestamp(self):
        pp = self._create(None, {"date": 315529200})
        pp.prepare(self.pathfmt)
        pp.run(self.pathfmt)
        self.assertEqual(self.pathfmt.kwdict["_mtime"], 315529200)

    def test_mtime_custom(self):
        pp = self._create({"key": "foo"}, {"foo": 315529200})
        pp.prepare(self.pathfmt)
        pp.run(self.pathfmt)
        self.assertEqual(self.pathfmt.kwdict["_mtime"], 315529200)


class ZipTest(BasePostprocessorTest):

    def test_zip_default(self):
        pp = self._create()
        self.assertEqual(pp.path, self.pathfmt.realdirectory)
        self.assertEqual(pp.run, pp._write)
        self.assertEqual(pp.delete, True)
        self.assertFalse(hasattr(pp, "args"))
        self.assertEqual(pp.zfile.compression, zipfile.ZIP_STORED)
        self.assertEqual(
            pp.zfile.filename, self.pathfmt.realdirectory + ".zip")

    def test_zip_options(self):
        pp = self._create({
            "keep-files": True,
            "compression": "zip",
            "extension": "cbz",
        })
        self.assertEqual(pp.delete, False)
        self.assertEqual(pp.zfile.compression, zipfile.ZIP_DEFLATED)
        self.assertEqual(
            pp.zfile.filename, self.pathfmt.realdirectory + ".cbz")

    def test_zip_safe(self):
        pp = self._create({"mode": "safe"})
        self.assertEqual(pp.delete, True)
        self.assertEqual(pp.path, self.pathfmt.realdirectory)
        self.assertEqual(pp.run, pp._write_safe)
        self.assertEqual(pp.args, (
            pp.path + ".zip", "a", zipfile.ZIP_STORED, True
        ))


if __name__ == "__main__":
    unittest.main()
