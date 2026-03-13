from unittest.mock import MagicMock, patch


class TestDnsModule:
    @patch("mikrotik.dns.pool.get_api")
    def test_get_dns_static_maps_fields(self, mock_get_api):
        from mikrotik.dns import get_dns_static

        api = MagicMock()
        mock_get_api.return_value = api
        api.path.return_value = iter([
            {
                ".id": "*1",
                "name": "srv.local",
                "address": "192.168.3.10",
                "ttl": "1d",
                "disabled": "true",
                "comment": "server",
            }
        ])

        rows = get_dns_static.__wrapped__.__wrapped__()
        assert rows == [
            {
                "id": "*1",
                "name": "srv.local",
                "address": "192.168.3.10",
                "ttl": "1d",
                "disabled": True,
                "comment": "server",
            }
        ]

    @patch("mikrotik.dns.pool.get_api")
    def test_add_dns_static_with_and_without_comment(self, mock_get_api):
        from mikrotik.dns import add_dns_static

        api = MagicMock()
        path_obj = MagicMock()
        mock_get_api.return_value = api
        api.path.return_value = path_obj

        assert add_dns_static("a.local", "192.168.3.20", "") is True
        path_obj.add.assert_called_with(name="a.local", address="192.168.3.20")

        assert add_dns_static("b.local", "192.168.3.21", "printer") is True
        path_obj.add.assert_called_with(
            name="b.local", address="192.168.3.21", comment="printer"
        )

    @patch("mikrotik.dns.pool.get_api")
    def test_remove_dns_static(self, mock_get_api):
        from mikrotik.dns import remove_dns_static

        api = MagicMock()
        path_obj = MagicMock()
        mock_get_api.return_value = api
        api.path.return_value = path_obj

        assert remove_dns_static("*9") is True
        path_obj.remove.assert_called_once_with("*9")


class TestFirewallModule:
    @patch("mikrotik.firewall.pool.get_api")
    def test_get_firewall_rules_maps_fields(self, mock_get_api):
        from mikrotik.firewall import get_firewall_rules

        api = MagicMock()
        mock_get_api.return_value = api
        api.path.return_value = iter([
            {
                ".id": "*1",
                "chain": "forward",
                "action": "drop",
                "src-address": "10.0.0.1",
                "dst-address": "1.1.1.1",
                "protocol": "tcp",
                "dst-port": "443",
                "in-interface": "ether2",
                "out-interface": "ether1",
                "comment": "block",
                "disabled": "false",
                "bytes": 123,
                "packets": 7,
            }
        ])

        rules = get_firewall_rules.__wrapped__.__wrapped__("filter")
        assert len(rules) == 1
        assert rules[0]["id"] == "*1"
        assert rules[0]["disabled"] is False
        assert rules[0]["bytes"] == "123"
        assert rules[0]["packets"] == "7"

    @patch("mikrotik.firewall.pool.get_api")
    def test_toggle_firewall_rule(self, mock_get_api):
        from mikrotik.firewall import toggle_firewall_rule

        api = MagicMock()
        fw = MagicMock()
        mock_get_api.return_value = api
        api.path.return_value = fw

        assert toggle_firewall_rule("*2", chain_type="nat", disabled=True) is True
        fw.update.assert_called_once_with(**{".id": "*2", "disabled": "true"})

    @patch("mikrotik.firewall.pool.get_api")
    def test_block_ip_updates_existing(self, mock_get_api):
        from mikrotik.firewall import block_ip

        api = MagicMock()
        addr_list = MagicMock()
        mock_get_api.return_value = api
        api.path.return_value = addr_list
        addr_list.__iter__.return_value = iter(
            [{".id": "*A", "address": "192.168.3.3", "list": "auto_block"}]
        )

        assert block_ip("192.168.3.3", "manual", "auto_block") is True
        addr_list.update.assert_called_once_with(**{".id": "*A", "comment": "manual"})
        addr_list.add.assert_not_called()

    @patch("mikrotik.firewall.pool.get_api")
    def test_block_ip_adds_new_when_not_exists(self, mock_get_api):
        from mikrotik.firewall import block_ip

        api = MagicMock()
        addr_list = MagicMock()
        mock_get_api.return_value = api
        api.path.return_value = addr_list
        addr_list.__iter__.return_value = iter([])

        assert block_ip("192.168.3.4", "auto", "auto_block") is True
        addr_list.add.assert_called_once_with(
            list="auto_block", address="192.168.3.4", comment="auto"
        )

    @patch("mikrotik.firewall.pool.get_api")
    def test_unblock_ip_found_and_not_found(self, mock_get_api):
        from mikrotik.firewall import unblock_ip

        api = MagicMock()
        addr_list = MagicMock()
        mock_get_api.return_value = api
        api.path.return_value = addr_list

        addr_list.__iter__.return_value = iter([])
        assert unblock_ip("192.168.3.5", "auto_block") is False

        addr_list.__iter__.return_value = iter(
            [
                {".id": "*1", "address": "192.168.3.5", "list": "auto_block"},
                {".id": "*2", "address": "192.168.3.5", "list": "auto_block"},
            ]
        )
        assert unblock_ip("192.168.3.5", "auto_block") is True
        assert addr_list.remove.call_count == 2


class TestQueueModule:
    @patch("mikrotik.queue.pool.get_api")
    def test_get_simple_queues_maps_rows(self, mock_get_api):
        from mikrotik.queue import get_simple_queues

        api = MagicMock()
        mock_get_api.return_value = api
        api.path.return_value = iter(
            [
                {
                    ".id": "*1",
                    "name": "Queue-1",
                    "target": "192.168.3.10/32",
                    "max-limit": "10M/10M",
                    "rate": "1000/2000",
                    "comment": "server",
                }
            ]
        )

        rows = get_simple_queues.__wrapped__.__wrapped__()
        assert rows[0][".id"] == "*1"
        assert rows[0]["name"] == "Queue-1"
        assert rows[0]["rate"] == "1000/2000"

    @patch("mikrotik.queue.pool.get_api")
    def test_get_top_queues_sorted_and_limited(self, mock_get_api):
        from mikrotik.queue import get_top_queues

        api = MagicMock()
        mock_get_api.return_value = api
        api.path.return_value = iter(
            [
                {"name": "Q1", "target": "192.168.3.1/32", "rate": "100/200"},
                {"name": "Q2", "target": "192.168.3.2/32", "rate": "1000/2000"},
                {"name": "Q3", "target": "192.168.3.3/32", "rate": "oops"},
                {"name": "Q4", "target": "192.168.3.4/32", "rate": "0/0"},
            ]
        )

        rows = get_top_queues(limit=1)
        assert len(rows) == 1
        assert rows[0]["name"] == "Q2"
        assert rows[0]["total_rate"] == 3000
        assert rows[0]["total_rate_fmt"].endswith("ps")

    @patch("mikrotik.queue.pool.get_api")
    def test_remove_simple_queue(self, mock_get_api):
        from mikrotik.queue import remove_simple_queue

        api = MagicMock()
        queue_obj = MagicMock()
        mock_get_api.return_value = api
        api.path.return_value = queue_obj

        assert remove_simple_queue("*11") is True
        queue_obj.remove.assert_called_once_with("*11")


class TestSchedulerModule:
    @patch("mikrotik.scheduler.pool.get_api")
    def test_get_schedulers_and_set_status(self, mock_get_api):
        from mikrotik.scheduler import get_schedulers, set_scheduler_status

        api = MagicMock()
        sched_obj = MagicMock()
        mock_get_api.return_value = api

        def _path(*parts):
            if parts == ("system", "scheduler"):
                return sched_obj
            return MagicMock()

        api.path.side_effect = _path
        sched_obj.__iter__.return_value = iter(
            [
                {
                    ".id": "*1",
                    "name": "daily-backup",
                    "start-date": "mar/10/2026",
                    "start-time": "01:00:00",
                    "interval": "1d",
                    "on-event": "/system backup save",
                    "run-count": "3",
                    "next-run": "mar/11/2026 01:00:00",
                    "disabled": "true",
                    "comment": "auto",
                }
            ]
        )

        rows = get_schedulers.__wrapped__.__wrapped__()
        assert rows[0]["id"] == "*1"
        assert rows[0]["disabled"] is True

        assert set_scheduler_status("*1", disabled=False) is True
        sched_obj.update.assert_called_once_with(**{".id": "*1", "disabled": "false"})
