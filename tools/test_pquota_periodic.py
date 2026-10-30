"""Exhaustive quota boot, fence and recovery matrices for the periodic tier."""
from test_pquota import *


class PeriodicPquotaTests(PquotaTests):
    def test_review_1_reboot_refuses_enabled_retained_or_triggered_producer(self):
        self.retained()
        self.prepare()
        scenarios = [
            dict(enablement={'after-landing.service': 'enabled'}),
            dict(unit_properties={'after-landing.service': 'LoadState=loaded\nActiveState=inactive\nSubState=dead\nUnitFileState=disabled\nWantedBy=default.target\nTriggeredBy=\n'}),
            dict(unit_files=[{'unit_file': 'producer.timer', 'state': 'enabled'}],
                 unit_properties={'producer.timer': 'LoadState=loaded\nActiveState=inactive\nUnitFileState=enabled\nTriggers=after-landing.service\nWantedBy=timers.target\n'}),
            dict(unit_files=[{'unit_file': 'producer.path', 'state': 'enabled'}],
                 unit_properties={'producer.path': 'LoadState=loaded\nActiveState=active\nUnitFileState=enabled\nTriggers=after-landing.service\nWantedBy=default.target\n'}),
        ]
        for scenario in scenarios:
            with self.subTest(scenario=scenario):
                self.controls(enablement={}, unit_properties={}, unit_files=[])
                self.controls(**scenario)
                self.assert_refuses(self.tool.reboot)


    def test_review_2_conflicting_or_unresolved_boot_root_refuses_before_write(self):
        config = self.tool.read('/boot/grub/grub.cfg')
        for root in ('/dev/sdb1', 'UUID=unknown'):
            with self.subTest(root=root):
                self.put('boot/grub/grub.cfg', config.replace('/dev/sda1', root))
                self.assert_refuses()
                self.assertFalse(self.tool.path(self.mod.ORIGINAL).exists())
                self.assertFalse(self.tool.path(self.mod.STATE).exists())
        self.put('boot/grub/grub.cfg', config)
        self.put('etc/fstab', '/dev/sdb1 / xfs defaults 0 1\n')
        self.assert_refuses()


    def test_review_3_incomplete_new_boot_proof_never_reaches_probe(self):
        self.healthy_boot()
        before = {name: self.tool.read(name) for name in
                  (self.mod.BOOT, '/proc/cmdline', '/etc/default/grub')}
        probe = self.patch(self.tool, 'probe', return_value={'inherited': True})
        changes = [(self.mod.BOOT, ''), (self.mod.BOOT, 'not-a-uuid'),
                   ('/proc/cmdline', 'root=/dev/sda1 ro rootflags=pquota'),
                   ('/proc/cmdline', before['/proc/cmdline'] + ' unexpected=1'),
                   ('/etc/default/grub', before['/etc/default/grub'] + 'GRUB_TIMEOUT=8\n')]
        for name, value in changes:
            with self.subTest(name=name, value=value):
                self.put(name.lstrip('/'), value)
                probe.reset_mock()
                ok, output = self.output(self.tool.verify)
                self.assertFalse(ok, output)
                probe.assert_not_called()
                self.put(name.lstrip('/'), before[name])
        for change in (dict(kernel='alternate'), dict(mount=dict(self.control['mount'], source='/dev/sdb1'))):
            with self.subTest(change=change):
                self.controls(**change)
                probe.reset_mock()
                ok, output = self.output(self.tool.verify)
                self.assertFalse(ok, output)
                probe.assert_not_called()
                self.controls(kernel='fixture', mount=dict(target='/', source='/dev/sda1', fstype='xfs', options='rw,prjquota'))


    def test_review_4_shell_input_refuses_before_any_boot_write(self):
        original = self.tool.read('/etc/default/grub')
        for filename in ('etc/default/grub', 'etc/default/grub.d/custom.cfg'):
            for line in ('GRUB_TIMEOUT=$(some-command)', 'GRUB_TIMEOUT=`some-command`',
                         'GRUB_TIMEOUT=${OTHER}', 'export GRUB_CMDLINE_LINUX="x"',
                         'source /other', '. /other', 'f() { true; }', 'if true; then true; fi'):
                with self.subTest(filename=filename, line=line):
                    self.put(filename, (original if filename.endswith('/grub') else '') + line + '\n')
                    self.assert_refuses()
                    self.assertFalse(self.tool.path(self.mod.ORIGINAL).exists())
                    self.assertFalse(self.tool.path(self.mod.STATE).exists())
            if filename.endswith('/grub'):
                self.put(filename, original)
            else:
                (self.root / filename).unlink()


    def test_review_5_manifest_omission_refuses_restore_and_original_verification(self):
        self.put('etc/default/grub.d/local.cfg', 'GRUB_TIMEOUT=5\n')
        self.prepare()
        path = self.tool.path(self.mod.ORIGINAL + '/manifest.json')
        original = path.read_text()
        for name in ('/etc/fstab', '/etc/default/grub', '/boot/grub/grub.cfg', '/etc/default/grub.d/local.cfg'):
            with self.subTest(name=name):
                manifest = json.loads(original)
                del manifest['files'][name]
                self.put(str(path.relative_to(self.root)), json.dumps(manifest))
                self.assert_refuses(self.tool.rollback)
                with self.assertRaises(ValueError):
                    self.tool.verify_originals(manifest)
                self.put(str(path.relative_to(self.root)), original)


    def test_review_disabled_service_and_triggers_remain_recorded_through_acceptance(self):
        self.retained()
        self.controls(unit_files=[{'unit_file': 'producer.timer', 'state': 'disabled'}],
            unit_properties={'producer.timer': 'LoadState=loaded\nActiveState=inactive\nSubState=dead\nUnitFileState=disabled\nWantedBy=\nTriggers=after-landing.service\n'})
        self.healthy_boot()
        ok, output = self.output(self.tool.verify)
        self.assertTrue(ok, output)
        checks = self.tool.state()['verification']['checks']
        prevention = next(c['detail'] for c in checks if c['name'] == 'owner boot prevention preserved')
        self.assertEqual(prevention['units']['after-landing.service']['installation'], 'disabled')
        self.assertEqual(prevention['units']['producer.timer']['installation'], 'disabled')
        self.assertFalse(any('start' in row or 'enable' in row or 'disable' in row for row in self.calls()))


    def test_review_uuid_root_and_literal_configuration_are_supported(self):
        root = 'UUID=11111111-1111-1111-1111-111111111111'
        self.put('etc/fstab', root + ' / xfs defaults 0 1\n')
        config = self.tool.read('/boot/grub/grub.cfg')
        self.put('boot/grub/grub.cfg', config.replace('/dev/sda1', root))
        self.put('etc/default/grub.d/local.cfg', '# comment\n\nGRUB_TIMEOUT=5 # literal\nGRUB_DISTRIBUTOR="Debian GNU/Linux"\n')
        self.assertEqual(self.tool.boot_safety()['root_uuid'], root[5:])


    def test_review_changed_backup_or_missing_binding_skips_probe_and_restore(self):
        self.healthy_boot()
        manifest_path = self.mod.ORIGINAL + '/manifest.json'
        manifest = self.tool.read(manifest_path)
        self.put(manifest_path.lstrip('/'), manifest + ' ')
        probe = self.patch(self.tool, 'probe', return_value=True)
        ok, output = self.output(self.tool.verify)
        self.assertFalse(ok, output)
        probe.assert_not_called()
        self.assert_refuses(self.tool.rollback)
        self.put(manifest_path.lstrip('/'), manifest)
        state = self.tool.state()
        del state['original_binding']
        self.tool.save(state)
        self.assert_refuses(self.tool.rollback)
        self.tool.path(self.mod.STATE).unlink()
        with self.assertRaises(ValueError):
            self.tool.verify_originals(json.loads(manifest))


    def test_repair_1_transitive_boot_dependencies_and_triggers_refuse(self):
        self.retained()
        self.prepare()
        def unit(**fields):
            base = dict(LoadState='loaded', ActiveState='inactive', SubState='dead', UnitFileState='disabled', WantedBy='', TriggeredBy='', Triggers='')
            base.update(fields)
            return ''.join(f'{key}={value}\n' for key, value in base.items())
        for relation in ('RequiredBy', 'PartOf'):
            with self.subTest(relation=relation):
                self.controls(unit_properties={'after-landing.service': unit(**{relation: 'middle.target'}),
                    'middle.target': unit(RequiredBy='default.target')})
                self.assert_refuses(self.tool.reboot)
        for relation in ('Requires', 'BindsTo', 'Upholds'):
            with self.subTest(relation=relation):
                self.controls(unit_properties={'default.target': unit(**{relation: 'middle.target'}),
                    'middle.target': unit(**{relation: 'after-landing.service'})})
                self.assert_refuses(self.tool.reboot)
        for suffix in ('timer', 'path', 'socket'):
            with self.subTest(trigger=suffix):
                name = 'producer.' + suffix
                self.controls(unit_files=[{'unit_file': name, 'state': 'enabled'}],
                    enablement={name: 'enabled'}, unit_properties={
                        name: unit(UnitFileState='enabled', Triggers='middle.target'),
                        'middle.target': unit(Requires='after-landing.service')})
                self.assert_refuses(self.tool.reboot)
        self.controls(unit_files=[], enablement={}, unit_properties={'default.target': unit(Requires='unresolved.target')},
                      graph_error='unresolved.target')
        self.assert_refuses(self.tool.reboot)


    def test_repair_2_real_grub_boot_image_metadata_is_accepted(self):
        kernel = '/boot/vmlinuz-fixture'
        root = 'UUID=11111111-1111-1111-1111-111111111111'
        self.controls(generated_kernel=kernel, generated_root=root)
        self.put('etc/fstab', root + ' / xfs defaults 0 1\n')
        self.put('boot/grub/grub.cfg', 'set default="0"\nmenuentry "Debian" {\n linux ' + kernel + ' root=' + root + ' ro console=ttyS0\n}\n')
        self.prepare()
        self.put('proc/sys/kernel/random/boot_id', 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb\n')
        self.put('proc/cmdline', 'BOOT_IMAGE=' + kernel + ' root=' + root + ' ro console=ttyS0 rootflags=pquota\n')
        self.controls(mount=dict(self.control['mount'], options='rw,prjquota'),
                      quota='Project quota state on / (/dev/sda1)\n Accounting: ON\n Enforcement: ON\n')
        probe = self.patch(self.tool, 'probe', return_value={'inherited': True})
        ok, output = self.output(self.tool.verify)
        self.assertTrue(ok, output)
        probe.assert_called_once()


    def test_repair_3_plan_under_read_only_root_never_writes_blkid_cache(self):
        self.controls(cache_probe=True)
        (self.root / 'run/blkid').mkdir(parents=True)
        with tempfile.TemporaryDirectory(prefix='pquota-plan-observer-') as directory:
            log = Path(directory) / 'calls.jsonl'
            self.tool.env = dict(self.env, PQUOTA_CALLS_FILE=str(log))
            modes = {path: path.stat().st_mode & 0o777 for path in [self.root, *self.root.rglob('*')]}
            try:
                for path, mode in modes.items(): path.chmod(mode & ~0o222)
                before = self.snapshot()
                _, output = self.output(self.tool.plan)
                self.assertEqual(before, self.snapshot())
                self.assertIn('boot safety: {', output)
                calls = [json.loads(line) for line in log.read_text().splitlines()]
                probes = [row for row in calls if row[0] == 'blkid']
                self.assertTrue(probes)
                for row in probes:
                    self.assertIn('-p', row)
                    self.assertEqual(row[row.index('-c') + 1], '/dev/null')
            finally:
                for path, mode in modes.items(): path.chmod(mode)


    def test_repair_4_save_default_refuses_before_writes(self):
        self.put('etc/default/grub', self.tool.read('/etc/default/grub') + 'GRUB_SAVEDEFAULT=true\n')
        self.assert_refuses()
        self.assertFalse(self.tool.path(self.mod.ORIGINAL).exists())
        self.assertFalse(self.tool.path(self.mod.STATE).exists())


    def test_repair_5_real_bootstrap_guard_has_bound_interruption_recovery(self):
        module = load('bootstrap_recovery_fixture', ROOT / 'fleet/bootstrap/bootstrap.py')
        bootstrap = module.Bootstrap(argparse.Namespace(dry_run=False, host='hetzner7'))
        original = self.tool.boot_files()
        for phase in ('after-dropin', 'after-update-grub'):
            with self.subTest(phase=phase):
                self.controls(fail=['update-grub'] if phase == 'after-dropin' else [])
                def command(*args):
                    self.tool.run(*args)
                    raise ValueError('interrupted after regeneration')
                with patch.object(module.runpy, 'run_path', return_value={'Pquota': lambda host: self.tool}), \
                        patch.object(bootstrap, 'write', side_effect=self.tool.write), \
                        patch.object(bootstrap, 'run', side_effect=command), \
                        contextlib.redirect_stdout(io.StringIO()), self.assertRaises(ValueError):
                    bootstrap.pquota({'pquota': True})
                self.controls(fail=[])
                self.output(self.tool.rollback)
                self.assertEqual(original, self.tool.boot_files())
                self.assertTrue(self.tool.verify_originals(self.tool.originals()))
                self.tool.path(self.mod.STATE).unlink()
                shutil.rmtree(self.tool.path(self.mod.ORIGINAL))


    def test_repair_graph_direction_cycles_incomplete_properties_and_bound(self):
        self.retained()
        def unit(**fields):
            base = dict(LoadState='loaded', ActiveState='inactive', SubState='dead', UnitFileState='disabled')
            base.update(fields)
            return ''.join(f'{key}={value}\n' for key, value in base.items())
        self.controls(unit_properties={'default.target': unit(Requires='basic.target'),
            'basic.target': unit(Requires='default.target'),
            'after-landing.service': unit(Requires='basic.target')})
        result = self.tool.boot_prevention(self.tool.services())
        self.assertNotIn('after-landing.service', result['reached'])
        self.controls(graph_incomplete='basic.target')
        with self.assertRaisesRegex(ValueError, 'incomplete activation graph'):
            self.tool.boot_prevention(self.tool.services())
        self.controls(graph_incomplete=None, unit_properties={
            'default.target': unit(Requires='a.target'), 'a.target': unit(Requires='b.target'),
            'b.target': unit(Requires='c.target'), 'c.target': unit()})
        with patch.object(self.mod, 'GRAPH_LIMIT', 4), self.assertRaisesRegex(ValueError, 'unit bound'):
            self.tool.boot_prevention(self.tool.services())


    def test_repair_boot_image_mismatch_duplicates_and_option_changes_skip_probe(self):
        self.healthy_boot()
        options = self.tool.read('/proc/cmdline').strip()
        metadata = 'BOOT_IMAGE=/vmlinuz-fixture'
        probe = self.patch(self.tool, 'probe', return_value=True)
        for line in ('BOOT_IMAGE=/vmlinuz-other ' + options,
                     metadata + ' ' + metadata + ' ' + options,
                     options + ' ' + metadata,
                     metadata + ' ' + options.replace('root=/dev/sda1 ro', 'ro root=/dev/sda1'),
                     metadata + ' ' + options + ' rootflags=pquota'):
            with self.subTest(cmdline=line):
                self.put('proc/cmdline', line + '\n')
                probe.reset_mock()
                ok, output = self.output(self.tool.verify)
                self.assertFalse(ok, output)
                probe.assert_not_called()


    def test_repair_save_default_dropin_saved_default_and_saved_entry_refuse(self):
        original = self.tool.read('/etc/default/grub')
        self.put('etc/default/grub.d/local.cfg', 'GRUB_SAVEDEFAULT="true"\n')
        self.assert_refuses()
        (self.root / 'etc/default/grub.d/local.cfg').unlink()
        self.put('etc/default/grub', original.replace('GRUB_DEFAULT=0', 'GRUB_DEFAULT=saved'))
        self.assert_refuses()
        self.put('etc/default/grub', original)
        self.controls(grubenv='saved_entry=0\n')
        self.assert_refuses()
        self.assertFalse(self.tool.path(self.mod.ORIGINAL).exists())
        self.assertFalse(self.tool.path(self.mod.STATE).exists())


    def test_repair_real_bootstrap_saves_binding_before_dropin_and_remains_recovery_only(self):
        module = load('bootstrap_complete_fixture', ROOT / 'fleet/bootstrap/bootstrap.py')
        bootstrap = module.Bootstrap(argparse.Namespace(dry_run=False, host='hetzner7'))
        original = self.tool.boot_files()
        witnessed = []
        def write(name, content):
            state = self.tool.state()
            self.assertIn(state['phase'], ('preparing', 'prepared'))
            self.assertEqual(state['transaction_origin'], 'bootstrap')
            manifest = self.tool.originals(require_binding=True)
            self.assertEqual(sorted(original), state['original_binding']['files'])
            self.assertEqual(set(manifest['files']), set(original))
            witnessed.append(state['original_binding'])
            self.tool.write(name, content)
        with patch.object(module.runpy, 'run_path', return_value={'Pquota': lambda host: self.tool}), \
                patch.object(bootstrap, 'write', side_effect=write), \
                patch.object(bootstrap, 'run', side_effect=self.tool.run):
            self.output(lambda: bootstrap.pquota({'pquota': True}))
            first = self.tool.state()
            self.output(lambda: bootstrap.pquota({'pquota': True}))
            self.assertEqual(first, self.tool.state())
        self.assertEqual(len(witnessed), 2)
        self.assertEqual(self.tool.state()['phase'], 'prepared')
        self.assert_refuses(self.tool.reboot)
        self.assert_refuses(self.tool.verify)
        self.output(self.tool.rollback)
        self.assertEqual(original, self.tool.boot_files())


    def test_third_on_failure_boot_handler_refuses_reboot(self):
        self.handler_reboot_fixture('OnFailure')


    def test_third_on_success_boot_handler_refuses_reboot(self):
        self.handler_reboot_fixture('OnSuccess')


    def test_third_root_slice_chain_uses_terminated_unit_operands(self):
        self.retained()
        self.controls(unit_properties={
            'default.target': 'LoadState=loaded\nActiveState=active\nUnitFileState=static\nRequires=app.slice\n',
            'app.slice': 'LoadState=loaded\nActiveState=active\nUnitFileState=static\nRequires=-.slice\n',
            '-.slice': 'LoadState=loaded\nActiveState=active\nUnitFileState=static\n'})
        result = self.tool.boot_prevention(self.tool.services())
        self.assertIn('-.slice', result['units'])
        self.assertIn('-.slice', result['reached'])
        for action in ('show', 'is-enabled'):
            calls = [row for row in self.calls() if row[0] == 'systemctl' and action in row and '-.slice' in row]
            self.assertTrue(calls)
            for row in calls:
                self.assertLess(row.index('--'), row.index('-.slice'))
                self.assertTrue(all(not token.startswith('--') for token in row[row.index('--') + 1:]))


    def test_third_handler_reverse_evidence_and_intermediate_targets_refuse(self):
        self.retained()
        def unit(**fields):
            status = dict(LoadState='loaded', ActiveState='inactive', SubState='dead', UnitFileState='disabled')
            status.update(fields)
            return ''.join(f'{key}={value}\n' for key, value in status.items())
        for event in ('OnFailure', 'OnSuccess'):
            with self.subTest(event=event, evidence='reverse-only dormant handler'):
                self.controls(unit_properties={'after-landing.service': unit(**{event + 'Of': 'handler.service'}),
                    'handler.service': unit()})
                with self.assertRaisesRegex(ValueError, 'success/failure handler'):
                    self.tool.boot_prevention(self.tool.services())
            with self.subTest(event=event, evidence='intermediate target'):
                self.controls(unit_properties={'default.target': unit(Requires='handler.service'),
                    'handler.service': unit(**{event: 'middle.target'}),
                    'middle.target': unit(Requires='after-landing.service')})
                with self.assertRaisesRegex(ValueError, 'success/failure handler'):
                    self.tool.boot_prevention(self.tool.services())


    def test_third_unsupported_handler_modes_and_templates_refuse(self):
        self.retained()
        status = 'LoadState=loaded\nActiveState=inactive\nUnitFileState=disabled\n'
        for event in ('OnSuccess', 'OnFailure'):
            for mode in ('isolate', 'flush', ''):
                with self.subTest(event=event, mode=mode):
                    self.controls(unit_properties={'default.target': status + 'Requires=handler.service\n',
                        'handler.service': status + event + '=cleanup.service\n' + event + 'JobMode=' + mode + '\n'})
                    with self.assertRaisesRegex(ValueError, 'unsupported .* handler job mode'):
                        self.tool.boot_prevention(self.tool.services())
        self.controls(unit_properties={'default.target': status + 'OnFailure=handler@.service\n'})
        with self.assertRaisesRegex(ValueError, 'unsupported activation graph unit'):
            self.tool.boot_prevention(self.tool.services())


    def test_third_benign_handlers_and_realistic_option_parsing(self):
        self.retained()
        self.controls(unit_properties={'default.target':
            'LoadState=loaded\nActiveState=active\nUnitFileState=static\nOnFailure=cleanup.service\n'})
        result = self.tool.boot_prevention(self.tool.services())
        self.assertIn(['default.target', 'cleanup.service', 'OnFailure'], result['handlers'])
        self.assertIn('cleanup.service', result['handler_reached'])
        self.assertNotIn('after-landing.service', result['handler_reached'])
        for row in self.calls():
            if row[0] == 'systemctl':
                self.assertIn('--', row)
                self.assertTrue(all(not value.startswith('--') for value in row[row.index('--') + 1:]))
        for action in ('show', 'is-enabled'):
            with self.subTest(action=action), self.assertRaisesRegex(ValueError, 'unrecognized option -.slice'):
                self.tool.user('systemctl', '--user', action, '-.slice')
        self.assertEqual(self.tool.unit('-.slice')['LoadState'], 'loaded')


    def test_plan_is_read_only_shows_occupancy_sources_environment_services(self):
        before = self.snapshot()
        _, output = self.output(self.tool.plan)
        for text in (self.mod.CONTENT, 'PASS occupancy hetzner7:1', 'PASS occupancy hetzner7:4',
                     'fabrig_head', 'PLAN_MIN_DISK_GB', 'qa-watch.service', 'would run: update-grub'):
            self.assertIn(text, output)
        self.assertEqual(before, self.snapshot())
        self.assertFalse(any(r[0] == 'update-grub' or r == ['systemctl', 'reboot', '--'] for r in self.calls()))
        self.assertFalse(any(r[0] == 'xfs_quota' and r[-2] != 'state' for r in self.calls()))


    def test_plan_without_options_shows_every_missing_occupancy_and_digest(self):
        self.tool.policy = {}
        self.put('claims.txt', 'hetzner7 1 [pool]: free\n' + self.held('4', 'other') + 'hetzner3 1 [pool]: free\n')
        _, output = self.output(self.tool.plan)
        self.assertIn('FAIL occupancy hetzner7:1', output)
        self.assertIn('FAIL occupancy hetzner7:4', output)
        self.assertIn(self.digest_inventory(), output)
        self.assertIn('missing/changed --inventory-digest', output)


    def test_full_occupancy_passes_and_records_claim_incarnations(self):
        value = self.tool.claims()
        self.assertEqual(len(value['slots']), 2)
        self.assertTrue(all(row['kind'] == 'maintenance' for row in value['slots']))
        self.assertTrue(all(row['created'] for row in value['slots']))


    def test_h8_without_eligible_slots_is_pinned_closed_not_a_free_slot(self):
        self.tool.host = 'hetzner8'
        result = self.tool.claims()
        self.assertEqual(result['slots'], [])
        self.assertTrue(result['admission_closed'])
        self.put('inventory.txt', (self.root / 'inventory.txt').read_text() + 'hetzner8 1=pool\n')
        self.put('claims.txt', (self.root / 'claims.txt').read_text() + 'hetzner8 1 [pool]: free\n')
        with self.assertRaises(ValueError): self.tool.claims()


    def test_free_slot_foreign_claim_wrong_what_and_unreadable_list_refuse(self):
        for row in ('hetzner7 1 [pool]: free\n', self.held('1', 'foreign'), self.held('1', what='wrong WHAT')):
            self.put('claims.txt', row + self.held('4') + 'hetzner3 1 [pool]: free\n')
            self.assert_refuses()
        self.controls(fail=['ssh'])
        self.assert_refuses()


    def test_changed_inventory_added_slot_changed_share_missing_or_duplicate_rows_refuse(self):
        self.policy['inventory_digest'] = '0' * 64
        self.assert_refuses()
        self.policy['inventory_digest'] = self.digest_inventory()
        original = (self.root / 'inventory.txt').read_text()
        listing = (self.root / 'claims.txt').read_text()
        for content, claims in ((original.replace('4=pool', '4=ops'), listing.replace('4 [pool]', '4 [ops]')),
                                (original.replace('4=pool', '4=pool 9=pool'), listing + self.held('9'))):
            self.put('inventory.txt', content)
            self.put('claims.txt', claims)
            self.assert_refuses()
        self.put('inventory.txt', original)
        for listing in ('', self.held('1'), self.held('1') * 2 + self.held('4')):
            self.put('claims.txt', listing)
            self.assert_refuses()


    def test_retained_owner_can_differ_from_approver_bound_post_recorded(self):
        self.retained()
        self.prepare()
        row = self.tool.state()['occupancy']['slots'][1]
        self.assertEqual(row['owner'], 'ops')
        self.assertEqual(row['approval']['approver'], 's/dynamic-memory')
        self.assertEqual(row['approval']['post'], 'POST-123')
        self.assertIn('after-landing.service', self.tool.state()['proof']['services']['owner_restarts'])


    def test_retained_approval_mismatches_refuse(self):
        post = self.retained()
        original = post.read_text()
        for content in (original.replace('s/dynamic-memory@hel8', 'caller@hel8'),
                        original.replace('POST-123', 'POST-other'), original.replace('hetzner7:4', 'hetzner7:1'),
                        original.replace('after-landing 20261029T1846Z', 'wrong WHAT'),
                        original.replace('plan:', 'missing:'), original.replace('preserve state and restart', 'TBD'),
                        original.replace('service: after-landing.service', 'service: other.service')):
            post.write_text(content)
            self.assert_refuses()
        post.write_text(original)
        self.policy['retained_claims'][0]['owner'] = 'other-owner'
        self.assert_refuses()


    def test_retained_approval_file_required_and_stopped_service_required(self):
        self.retained()
        files = self.policy['approval_files']
        self.policy['approval_files'] = {}
        self.assert_refuses()
        self.policy['approval_files'] = files
        self.controls(unit_states={'after-landing.service': 'active'})
        self.assert_refuses()


    def test_retained_service_restarted_or_post_changed_before_reboot_refuses(self):
        post = self.retained()
        self.prepare()
        self.controls(unit_states={'after-landing.service': 'active'})
        self.assert_refuses(self.tool.reboot)
        self.controls(unit_states={})
        post.write_text(post.read_text() + 'extra approval changed\n')
        self.assert_refuses(self.tool.reboot)


    def test_existing_rootflags_in_each_cmdline_or_dropin_refuse_without_backup(self):
        base = (self.root / 'etc/default/grub').read_text()
        for name in ('GRUB_CMDLINE_LINUX', 'GRUB_CMDLINE_LINUX_DEFAULT'):
            self.put('etc/default/grub', base + f'{name}="rootflags=noquota"\n')
            self.assert_refuses()
        self.put('etc/default/grub', base)
        self.put('etc/default/grub.d/other.cfg', 'GRUB_CMDLINE_LINUX="rootflags=prjquota"\n')
        self.assert_refuses()
        self.assertFalse(self.tool.path(self.mod.ORIGINAL).exists())


    def test_dynamic_or_unknown_boot_configuration_refuses(self):
        base = (self.root / 'etc/default/grub').read_text()
        for text in ('GRUB_CMDLINE_LINUX="$OTHER"', 'GRUB_CMDLINE_LINUX="$(unknown)"'):
            self.put('etc/default/grub', base + text + '\n')
            self.assert_refuses()
        self.put('etc/default/grub', base)
        self.put('etc/default/grub.d/unknown.cfg', '. /unknown/config\n')
        self.assert_refuses()


    def test_fstab_other_quota_or_duplicate_root_refuses(self):
        for option in ('pquota', 'prjquota', 'usrquota', 'grpquota', 'noquota', 'pqnoenforce'):
            self.put('etc/fstab', f'/dev/sda1 / xfs defaults,{option} 0 1\n')
            self.assert_refuses()
        self.put('etc/fstab', '/dev/sda1 / xfs defaults 0 1\n/dev/sdb / xfs defaults 0 1\n')
        self.assert_refuses()


    def test_unidentifiable_default_and_duplicate_linux_root_refuse(self):
        original = (self.root / 'boot/grub/grub.cfg').read_text()
        for text in (original.replace('set default="0"', 'set default="1"'), original.replace('root=/dev/sda1', 'root=/dev/sda1 root=/dev/sdb')):
            self.put('boot/grub/grub.cfg', text)
            self.assert_refuses()
        self.put('boot/grub/grub.cfg', original)
        self.controls(grubenv='next_entry=1\n')
        self.assert_refuses()


    def test_prepare_backup_once_atomic_dropin_idempotence_and_exact_options(self):
        original = self.tool.boot_files()
        self.prepare()
        manifest = self.tool.originals()
        self.assertEqual(set(manifest['files']), set(original))
        for name, content in original.items():
            self.assertEqual(self.tool.path(self.mod.ORIGINAL + '/files' + name).read_bytes(), content)
        before = self.snapshot()
        self.prepare()
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.tool.safe(self.mod.DROPIN).read_text(), self.mod.CONTENT)
        self.assertEqual(self.tool.state()['default_before'] + ' rootflags=pquota', self.tool.state()['default_after'])
        self.assertNotIn(['systemctl', 'reboot', '--'], self.calls())
        self.assertEqual(list(self.tool.path(self.mod.DROPIN).parent.glob('.90-fabrig*')), [])


    def test_corrupt_or_drifted_backup_is_never_overwritten(self):
        self.prepare()
        backup = self.tool.path(self.mod.ORIGINAL + '/files/etc/default/grub')
        backup.write_text('corrupt')
        self.assert_refuses()
        with self.assertRaises(ValueError): self.tool.originals()
        self.assertEqual(backup.read_text(), 'corrupt')


    def test_update_grub_failure_and_changed_existing_option_refuse_reboot(self):
        for change in (dict(fail=['update-grub']), dict(changed_options=True)):
            self.controls(**change)
            with self.assertRaises(ValueError), contextlib.redirect_stdout(io.StringIO()): self.tool.prepare()
            self.assertEqual(self.tool.state()['phase'], 'preparing')
            self.assert_refuses(self.tool.reboot)
            self.controls(fail=[], changed_options=False)
            self.output(self.tool.rollback)


    def test_rollback_restores_original_files_modes_digests_and_is_idempotent(self):
        original = self.tool.boot_files()
        self.prepare()
        self.put('etc/default/grub', 'GRUB_DEFAULT=0\n# edited\n')
        self.output(self.tool.rollback)
        self.assertEqual(self.tool.boot_files(), original)
        self.assertTrue(self.tool.verify_originals(self.tool.originals()))
        self.output(self.tool.rollback)
        self.assertEqual(self.tool.boot_files(), original)
        self.output(self.tool.reboot)
        self.assertIn(['systemctl', 'reboot', '--'], self.calls())


    def test_missing_backup_or_foreign_dropin_refuses_rollback(self):
        self.assert_refuses(self.tool.rollback)
        self.prepare()
        self.put(self.mod.DROPIN.lstrip('/'), '# foreign\n')
        self.assert_refuses(self.tool.rollback)


    def test_boot_and_marker_refusals(self):
        self.marker_uid = 1000
        self.assert_refuses()
        self.marker_uid = 0
        marker = self.tool.path('/var/lib/fabrig-pquota/fence')
        marker.chmod(0o666)
        self.assert_refuses()
        marker.chmod(0o600)
        with patch.object(self.mod.socket, 'gethostname', return_value='hetzner6'):
            self.assert_refuses()
        self.control['mount']['fstype'] = 'ext4'
        self.controls()
        self.assert_refuses()


    def test_all_heavy_queued_running_unknown_states_and_broken_status_refuse(self):
        for state in ('queued', 'submitted', 'waiting', 'launching', 'active', 'disk-retry', 'finishing', 'closing', 'unknown'):
            self.put('heavy.json', json.dumps(dict(version=1, installation={'boot':'b'}, tasks={'x': {'state':state}})))
            self.assert_refuses()
        self.controls(installed=2)
        self.assert_refuses()


    def test_heavy_scopes_submitters_codex_and_after_landing_user_units_refuse(self):
        for name in ('skein-heavy-abc-token.service', 'codex-run-123.service', 'after-landing.service', 'agents-after-landing@jig.service'):
            self.controls(units=[dict(unit=name, active='active')])
            self.assert_refuses()
        self.controls(units=[], submitters=[dict(pid=99, tool='heavy submitter/wrapper')])
        self.assert_refuses()


    def test_missing_preboot_source_or_environment_proof_refuses_before_backup(self):
        for changes in (dict(source_error=True), dict(source_error=False, env_error=True)):
            self.controls(**changes)
            self.assert_refuses()
        self.assertFalse(self.tool.path(self.mod.ORIGINAL).exists())


    def test_preboot_source_environment_and_service_proof_recorded_without_starting(self):
        self.prepare()
        state = self.tool.state()
        self.assertTrue(all(row['pass_result'] for row in state['fence']))
        self.assertTrue({'heavy idle', 'non-claim writers', 'central occupancy'} <= {row['name'] for row in state['fence']})
        self.assertEqual(state['proof']['sources'], self.control['sources'])
        self.assertEqual(state['proof']['environment'], self.control['machine'])
        self.assertEqual(state['proof']['services']['states']['qa-watch.service']['ActiveState'], 'active')
        self.assertIn('qa-watch.service', state['proof']['services']['owner_restarts'])
        self.assertFalse(any(r[0] == 'systemctl' and any(v in r for v in ('start','restart','stop')) for r in self.calls()))


    def test_secret_or_unknown_environment_keys_are_not_accepted_into_state(self):
        self.controls(machine={'PLAN_MIN_DISK_GB': '40', 'PRIVATE_TOKEN': 'PRIVATE FIXTURE'})
        self.assert_refuses()
        self.assertFalse(self.tool.path(self.mod.STATE).exists())


    def test_reboot_yes_and_prepare_required_then_new_claim_incarnation_refuses(self):
        for command in ('prepare','reboot','rollback'):
            with patch.object(sys, 'argv', ['pquota', command, '--host', 'hetzner7']), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                self.mod.main()
        self.assert_refuses(self.tool.reboot)
        self.prepare()
        self.put('claims.txt', self.held('1', created='2026-10-30T13:00:00+00:00') + self.held('4') + 'hetzner3 1 [pool]: free\n')
        self.assert_refuses(self.tool.reboot)


    def test_reboot_rechecks_heavy_nonclaim_writer_sources_and_environment(self):
        self.prepare()
        for key, value in (('submitters', [dict(pid=8)]), ('units', [dict(unit='codex-run-x.service',active='active')])):
            self.controls(**{key:value})
            self.assert_refuses(self.tool.reboot)
            self.controls(**{key:[]})
        sources = self.control['sources']
        self.controls(sources=dict(sources, fabrig_head='f' * 40))
        self.assert_refuses(self.tool.reboot)
        self.controls(sources=sources, machine={'PLAN_MIN_DISK_GB': '41'})
        self.assert_refuses(self.tool.reboot)


    def test_reboot_refuses_changed_boot_input_even_when_generated_cfg_unchanged(self):
        self.prepare()
        cfg = self.tool.digest()
        path = self.root / 'etc/default/grub'
        path.write_text(path.read_text() + 'GRUB_TIMEOUT=9\n')
        self.assertEqual(self.tool.digest(), cfg)
        self.assert_refuses(self.tool.reboot)


    def test_reboot_checks_fence_as_last_operations_then_boot_changes_refuse(self):
        self.prepare()
        self.output(self.tool.reboot)
        self.assertEqual(self.calls()[-1], ['systemctl', 'reboot', '--'])
        self.assertTrue(all(row['pass_result'] for row in self.tool.state()['reboot_fence']))
        self.assertEqual(self.calls()[-2][0], 'ssh')
        self.put('proc/sys/kernel/random/boot_id', 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb')
        self.assert_refuses(self.tool.reboot)


    def test_verify_passes_runs_probe_cleans_up_and_records_receipt(self):
        self.healthy_boot()
        ok, output = self.output(self.tool.verify)
        self.assertTrue(ok, output)
        self.assertNotIn('FAIL ', output)
        self.assertFalse(list(self.tool.path('/var/lib/fabrig-pquota/probe').iterdir()))
        self.assertTrue(self.tool.state()['verification']['checks'][-1]['detail']['inherited'])
        self.assertTrue(all(row['pass_result'] for row in self.tool.state()['verification']['fence']))
        commands = [row[row.index('-c')+1] for row in self.calls() if row[0] == 'xfs_quota']
        self.assertTrue(any(row.startswith('project -C') for row in commands))
        self.assertTrue(any('bhard=0' in row for row in commands))


    def test_verify_failed_boot_accounting_or_environment_skips_all_quota_mutation(self):
        self.healthy_boot()
        self.put('proc/sys/kernel/random/boot_id', 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa')
        self.controls(machine={'PLAN_MIN_DISK_GB': '99'}, quota='Project quota state on / (/dev/sda1)\n Accounting: OFF\n Enforcement: ON\n')
        before = len(self.calls())
        ok, output = self.output(self.tool.verify)
        self.assertFalse(ok)
        self.assertIn('FAIL boot changed', output)
        self.assertIn('FAIL machine.env', output)
        self.assertFalse(any(row[0] == 'xfs_quota' and 'project ' in row[row.index('-c')+1] for row in self.calls()[before:]))


    def test_verify_claim_changed_after_boot_or_source_drift_skips_probe(self):
        self.healthy_boot()
        self.put('claims.txt', self.held('1', 'foreign') + self.held('4') + 'hetzner3 1 [pool]: free\n')
        self.controls(sources=dict(self.control['sources'], agents_current='/fixture/other-release'))
        ok, output = self.output(self.tool.verify)
        self.assertFalse(ok)
        self.assertIn('FAIL installed sources unchanged', output)
        self.assertIn('FAIL maintenance and retained', output)


    def test_probe_requires_edquot_not_enospc_or_success_and_always_cleans(self):
        for code in (0, 28):
            self.controls(write_errno=code)
            with self.assertRaises(ValueError): self.tool.probe()
            self.assertFalse(list(self.tool.path('/var/lib/fabrig-pquota/probe').iterdir()))


    def test_probe_inheritance_and_partial_setup_failure_clean_up(self):
        self.controls(bad_inherit=True)
        with self.assertRaises(ValueError): self.tool.probe()
        self.controls(bad_inherit=False, probe_fail='cap')
        with self.assertRaises(ValueError): self.tool.probe()
        self.assertFalse(list(self.tool.path('/var/lib/fabrig-pquota/probe').iterdir()))
        self.assertTrue(any(row[0] == 'xfs_quota' and 'project -C' in row[row.index('-c')+1] for row in self.calls()))


    def test_probe_cleanup_failure_is_failure_and_preserves_evidence_directory(self):
        self.controls(probe_fail='clear')
        with self.assertRaisesRegex(ValueError, 'cleanup incomplete'): self.tool.probe()
        self.assertTrue(list(self.tool.path('/var/lib/fabrig-pquota/probe').iterdir()))


    def test_probe_refuses_unreadable_project_inventory_or_collision_before_mutating(self):
        reports = ('garbage', 'Project quota on / (/dev/sda1)\n#1610612736 1 0 0\n')
        for report in reports:
            with patch.object(self.tool, 'run', return_value=report) as run, \
                    patch.object(self.mod.uuid, 'uuid4', return_value=argparse.Namespace(int=0)):
                with self.assertRaises(ValueError): self.tool.probe()
                self.assertEqual(run.call_count, 1)
                self.assertFalse(self.tool.path('/var/lib/fabrig-pquota/probe').exists())


    def test_new_child_project_must_inherit_and_failure_cleans(self):
        def attrs(path):
            project = json.loads((self.root / 'project.json').read_text())
            return dict(project=project + (path.name == 'child'), inherit=True)
        self.tool.project_attrs.side_effect = attrs
        with self.assertRaisesRegex(ValueError, 'did not inherit'): self.tool.probe()
        self.assertFalse(list(self.tool.path('/var/lib/fabrig-pquota/probe').iterdir()))


    def test_cli_parses_bound_claim_policy_and_rejects_duplicates_or_old_format(self):
        post = self.retained()
        argv = ['pquota', 'plan', '--host', 'hetzner7', '--inventory-digest', self.digest_inventory(),
                '--maintenance-owner', 'ops', '--maintenance-what', 'pquota maintenance REF',
                '--retained-claim', '4:ops:s/dynamic-memory:POST-123',
                '--approval-file', f'POST-123:{post}', '--retained-service', '4:after-landing.service']
        with patch.object(sys, 'argv', argv), patch.object(self.mod.os, 'geteuid', return_value=0), \
                patch.object(self.mod, 'Pquota', return_value=self.tool) as constructor:
            self.output(self.mod.main)
            self.assertEqual(constructor.call_args.kwargs['policy'], self.policy)
        for extra in (['--retained-claim', '4:ops:old-three-fields'],
                      ['--retained-claim', '4:ops:s/dynamic-memory:POST-123'],
                      ['--inventory-digest', 'bad-digest']):
            with patch.object(sys, 'argv', argv + extra), patch.object(self.mod.os, 'geteuid', return_value=0), \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                self.mod.main()



def load_tests(loader, tests, pattern):
    cls = PeriodicPquotaTests
    return unittest.TestSuite(cls(name) for name in cls.__dict__ if name.startswith("test_"))
