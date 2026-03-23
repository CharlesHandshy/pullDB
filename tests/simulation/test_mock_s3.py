"""Tests for Mock S3 Client."""

import os
import sys

# Ensure we import from the local project, not system packages
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

import unittest

from pulldb.simulation.adapters.mock_s3 import MockS3Client, S3Error
from pulldb.simulation.core.state import get_simulation_state, reset_simulation


class TestMockS3Client(unittest.TestCase):
    def setUp(self):
        reset_simulation()
        self.state = get_simulation_state()
        self.client = MockS3Client()

    def test_list_keys(self):
        self.client.load_fixtures("my-bucket", ["backup1.sql", "backup2.sql", "other.txt"])
        
        keys = self.client.list_keys("my-bucket", "backup")
        self.assertEqual(len(keys), 2)
        self.assertIn("backup1.sql", keys)
        self.assertIn("backup2.sql", keys)
        
        keys = self.client.list_keys("my-bucket", "other")
        self.assertEqual(len(keys), 1)
        self.assertEqual(keys[0], "other.txt")

    def test_head_object(self):
        self.client.load_fixtures("my-bucket", ["file.txt"])
        
        meta = self.client.head_object("my-bucket", "file.txt")
        self.assertIn("ContentLength", meta)
        
        with self.assertRaises(S3Error) as ctx:
            self.client.head_object("my-bucket", "missing.txt")
        self.assertEqual(ctx.exception.response["Error"]["Code"], "404")

    def test_get_object(self):
        self.client.load_fixtures("my-bucket", ["file.txt"])
        
        obj = self.client.get_object("my-bucket", "file.txt")
        self.assertIn("Body", obj)
        
        body = obj["Body"]
        content = body.read()
        # Content is now unique per key
        self.assertIn(b"my-bucket/file.txt", content)
        body.close()
