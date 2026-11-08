# -*- coding: utf-8 -*-
"""0.4.0-dev4: corrected time entries and encrypted vault lifecycle UI.

All routes are dispatched after the main handler's authentication and CSRF checks.
"""
from __future__ import annotations
import re
from rk_dev3 import esc
from rk_dev3_core import rate_grosze
from rk_dev4_core import action_log, update_time, void_time, vault_rotate, vault_delete, vault_file_path


class Dev4Mixin:
    def dev4_get(self,path,qs):
        m=re.fullmatch(r'/worktime/(\d+)/edit',path)
        if m:self.dev4_time_edit_page(int(m.group(1)));return True
        return False

    def dev4_post(self,path,fields,files):
        m=re.fullmatch(r'/worktime/(\d+)/(update|delete)',path)
        if m:
            try:self.dev4_time_change(int(m.group(1)),m.group(2),fields)
            except ValueError as exc:self._dev3_error(exc)
            return True
        m=re.fullmatch(r'/vault/(\d+)/(rotate|delete)',path)
        if m:
            try:self.dev4_vault_change(int(m.group(1)),m.group(2),fields)
            except (ValueError,OSError) as exc:self._dev3_error(exc)
            return True
        return False

    def _dev4_time_row(self,con,entry_id,user):
        row=con.execute('SELECT * FROM dev3_time_entries WHERE id=?',(entry_id,)).fetchone()
        if not row:raise ValueError('Nie znaleziono wpisu czasu')
        if user['role']!='admin' and row['user_id']!=user['id']:
            raise ValueError('Brak dostępu do wpisu czasu')
        return row

    def dev4_time_edit_page(self,entry_id):
        app=self._dev3_app();user=self._dev3_me()
        try:
            with app.db() as con:
                row=self._dev4_time_row(con,entry_id,user)
                if con.execute('SELECT 1 FROM dev4_time_voids WHERE entry_id=?',(entry_id,)).fetchone():
                    raise ValueError('Ten wpis został już anulowany')
        except ValueError as exc:return self._dev3_error(exc,403)
        checked='checked' if row['billable'] else ''
        body=(f'<div class="topbar"><h1>Korekta czasu pracy #{entry_id}</h1></div>'
              f'<div class="card"><form method="post" action="/worktime/{entry_id}/update">'
              f'<label>Data</label><input type="date" name="day" required value="{esc(row["activity_date"])}">'
              f'<label>Minuty</label><input type="number" name="minutes" min="1" max="1440" required value="{int(row["minutes"])}">'
              f'<label>Stawka PLN/h</label><input type="number" name="rate" step="0.01" min="0" value="{row["rate_grosze"]/100:.2f}">'
              f'<label>Opis</label><textarea name="description">{esc(row["description"])}</textarea>'
              f'<label><input type="checkbox" name="billable" value="1" {checked}> Rozliczalne</label>'
              '<button class="btn primary">Zapisz korektę</button></form>'
              '<p class="small">Poprzednia wersja wpisu pozostanie w historii korekt.</p>'
              '<a class="btn" href="/worktime">Anuluj</a></div>')
        self._dev3_html('Korekta czasu',body,'worktime')

    def dev4_time_change(self,entry_id,kind,fields):
        app=self._dev3_app();user=self._dev3_me()
        with app.db() as con:
            row=self._dev4_time_row(con,entry_id,user)
            if kind=='delete':
                void_time(con,entry_id,user['id'],fields.get('reason',''))
            else:
                try:minutes=int(fields.get('minutes') or 0)
                except (ValueError,TypeError):raise ValueError('Nieprawidłowa liczba minut')
                update_time(con,entry_id,user['id'],fields.get('day',''),minutes,
                            fields.get('description',''),rate_grosze(fields.get('rate','0')),
                            bool(fields.get('billable')))
        self.redirect('/worktime')

    def dev4_vault_change(self,file_id,kind,fields):
        app=self._dev3_app();user=self._dev3_me()
        stored_name=None
        with app.db() as con:
            row=con.execute('SELECT * FROM dev3_vault_files WHERE id=?',(file_id,)).fetchone()
            if not row:raise ValueError('Plik sejfu nie istnieje')
            permitted=user['role']=='admin' or row['owner_id']==user['id']
            if not permitted:raise ValueError('Brak uprawnień do zmiany pliku')
            if kind=='rotate':
                vault_rotate(con,app.FILES_DIR,file_id,permitted,
                             fields.get('old_passphrase',''),fields.get('new_passphrase',''))
                action_log(con,row['case_id'],user['id'],'Zmiana hasła sejfu',f'Plik {file_id}')
            else:
                # Destructive operation requires a precise typed confirmation.
                if fields.get('confirmation')!='USUŃ':
                    raise ValueError('Wpisz USUŃ, aby usunąć plik sejfu')
                stored_name=row['stored_name']
                action_log(con,row['case_id'],user['id'],'Usunięcie pliku sejfu',f'Plik {file_id}')
                vault_delete(con,app.FILES_DIR,file_id,permitted)
        if stored_name:
            try:vault_file_path(app.FILES_DIR,stored_name).unlink(missing_ok=True)
            except OSError as exc:
                # Removed from DB but ciphertext remains: log for maintenance.
                app.log_app_exception('/vault/%s/delete-file'%file_id,exc)
        self.redirect('/vault')
