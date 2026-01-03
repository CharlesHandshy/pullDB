-- Migration: 081_disallowed_users.sql
-- Purpose: Table for admin-configurable disallowed usernames
-- 
-- This table stores usernames that are blocked from registration.
-- Works alongside hardcoded list in pulldb/domain/validation.py.
-- 
-- Design:
-- - `is_hardcoded` marks entries from initial seed (cannot be removed via UI)
-- - Entries can be added/removed by admins via CLI or Web UI
-- - All checks are case-insensitive (stored lowercase)

CREATE TABLE IF NOT EXISTS disallowed_users (
    username VARCHAR(100) NOT NULL PRIMARY KEY,
    reason VARCHAR(500) NULL,
    is_hardcoded BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    created_by CHAR(36) NULL,  -- User ID who added (NULL for hardcoded/seed)
    
    INDEX idx_disallowed_users_hardcoded (is_hardcoded),
    INDEX idx_disallowed_users_created (created_at)
);

-- Pre-populate with hardcoded system accounts
-- These mirror DISALLOWED_USERS_HARDCODED in validation.py
-- is_hardcoded=TRUE means they cannot be removed via admin UI

INSERT IGNORE INTO disallowed_users (username, reason, is_hardcoded, created_by) VALUES
-- Core system accounts
('root', 'System administrator account', TRUE, NULL),
('daemon', 'System daemon account', TRUE, NULL),
('bin', 'System binary owner', TRUE, NULL),
('sys', 'System account', TRUE, NULL),
('sync', 'System sync account', TRUE, NULL),
('games', 'Games pseudo-user', TRUE, NULL),
('man', 'Man page owner', TRUE, NULL),
('lp', 'Line printer daemon', TRUE, NULL),
('mail', 'Mail daemon', TRUE, NULL),
('news', 'News daemon', TRUE, NULL),
('uucp', 'UUCP daemon', TRUE, NULL),
('proxy', 'Proxy daemon', TRUE, NULL),
('backup', 'Backup daemon', TRUE, NULL),
('list', 'Mailing list manager', TRUE, NULL),
('irc', 'IRC daemon', TRUE, NULL),
('gnats', 'Bug reporting system', TRUE, NULL),
('nobody', 'Unprivileged user', TRUE, NULL),
-- Systemd accounts
('systemd-network', 'Systemd network daemon', TRUE, NULL),
('systemd-resolve', 'Systemd resolver', TRUE, NULL),
('systemd-timesync', 'Systemd time sync', TRUE, NULL),
('messagebus', 'D-Bus message daemon', TRUE, NULL),
('syslog', 'Syslog daemon', TRUE, NULL),
-- Package/service accounts
('_apt', 'APT package manager', TRUE, NULL),
('tss', 'TPM software stack', TRUE, NULL),
('uuidd', 'UUID daemon', TRUE, NULL),
('tcpdump', 'Network packet analyzer', TRUE, NULL),
('avahi-autoipd', 'Avahi autoip daemon', TRUE, NULL),
('usbmux', 'USB multiplexer', TRUE, NULL),
('rtkit', 'RealtimeKit daemon', TRUE, NULL),
('dnsmasq', 'DNS/DHCP server', TRUE, NULL),
('cups-pk-helper', 'CUPS policy kit helper', TRUE, NULL),
('speech-dispatcher', 'Speech synthesis daemon', TRUE, NULL),
('avahi', 'Avahi mDNS daemon', TRUE, NULL),
('kernoops', 'Kernel oops collector', TRUE, NULL),
('saned', 'SANE scanner daemon', TRUE, NULL),
('nm-openvpn', 'NetworkManager OpenVPN', TRUE, NULL),
('hplip', 'HP Linux Imaging', TRUE, NULL),
('whoopsie', 'Ubuntu error reporting', TRUE, NULL),
('colord', 'Color management daemon', TRUE, NULL),
('geoclue', 'Geolocation daemon', TRUE, NULL),
('pulse', 'PulseAudio daemon', TRUE, NULL),
('gnome-initial-setup', 'GNOME initial setup', TRUE, NULL),
('gdm', 'GNOME display manager', TRUE, NULL),
('sssd', 'System security services', TRUE, NULL),
-- Web/database service accounts
('www-data', 'Web server daemon', TRUE, NULL),
('mysql', 'MySQL server', TRUE, NULL),
('postgres', 'PostgreSQL server', TRUE, NULL),
('redis', 'Redis server', TRUE, NULL),
('nginx', 'Nginx web server', TRUE, NULL),
('apache', 'Apache web server', TRUE, NULL),
('apache2', 'Apache2 web server', TRUE, NULL),
('httpd', 'HTTP daemon', TRUE, NULL),
-- Cloud/VM accounts
('ubuntu', 'Ubuntu default user', TRUE, NULL),
('ec2-user', 'AWS EC2 default user', TRUE, NULL),
('admin', 'Generic admin account', TRUE, NULL),
-- Reserved pullDB names
('pulldb', 'pullDB service name', TRUE, NULL),
('pulldb_service', 'Service Bootstrap/CLI Admin Account (SBCACC)', TRUE, NULL),
('system', 'Reserved system name', TRUE, NULL),
('service', 'Reserved service name', TRUE, NULL),
('api', 'Reserved API name', TRUE, NULL),
('web', 'Reserved web name', TRUE, NULL),
('worker', 'Reserved worker name', TRUE, NULL),
('anonymous', 'Anonymous user concept', TRUE, NULL),
('guest', 'Guest user concept', TRUE, NULL),
('test', 'Test account name', TRUE, NULL),
('demo', 'Demo account name', TRUE, NULL);
