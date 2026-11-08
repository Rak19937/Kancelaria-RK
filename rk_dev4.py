# -*- coding: utf-8 -*-
"""0.4.0-dev4: corrected time entries and encrypted vault lifecycle UI.

All routes are dispatched after the main handler's authentication and CSRF checks.
"""
from __future__ import annotations
import re
import json
import os
import uuid
from rk_dev3 import esc
from rk_dev3_core import rate_grosze
from rk_dev4_core import action_log, update_time, void_time, vault_rotate, vault_delete, vault_file_path


class Dev4Mixin:
    def dev4_get(self,path,qs):
        if path=='/worktime/history':
            self.dev4_time_history(qs);return True
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

    def dev4_time_history(self,qs):
        app=self._dev3_app();user=self._dev3_me()
        try:page=max(1,min(10000,int((qs or {}).get('page',['1'])[0])))
        except (ValueError,TypeError,IndexError):page=1
        limit=50
        where='' if user['role']=='admin' else 'WHERE t.user_id=?'
        params=() if user['role']=='admin' else (user['id'],)
        with app.db() as con:
            total=con.execute('SELECT COUNT(*) FROM dev4_time_corrections h JOIN dev3_time_entries t ON t.id=h.entry_id '+where,params).fetchone()[0]
            rows=con.execute('''SELECT h.*,t.activity_date,t.description,t.minutes,t.rate_grosze,
                t.billable,t.case_id FROM dev4_time_corrections h
                JOIN dev3_time_entries t ON t.id=h.entry_id '''+where+
                ' ORDER BY h.id DESC LIMIT ? OFFSET ?',params+(limit,(page-1)*limit)).fetchall()
        out=['<div class="topbar"><h1>Historia korekt czasu pracy</h1><a class="btn" href="/worktime">Wróć</a></div><div class="card">']
        for r in rows:
            try:old=json.loads(r['previous_value'])
            except (ValueError,TypeError):old={}
            out.append('<div class="dev3-item"><b>Wpis #%s · korekta %s</b><p>Przed: %s · %s minut · %s</p><p>Aktualnie: %s · %s minut · %s</p><details><summary>Pozostałe poprzednie dane</summary><pre>%s</pre></details></div>'%(
                int(r['entry_id']),esc(r['created_at']),esc(old.get('activity_date','—')),
                esc(old.get('minutes','—')),esc(old.get('description','')),
                esc(r['activity_date']),esc(r['minutes']),esc(r['description']),
                esc(json.dumps(old,ensure_ascii=False,indent=2))))
        if not rows:out.append('<p>Brak korekt na tej stronie.</p>')
        out.append('<p>Strona %s · łączna liczba korekt: %s</p>'%(page,total))
        if page>1:out.append('<a class="btn small" href="/worktime/history?page=%s">← Poprzednia</a> '%(page-1))
        if page*limit<total:out.append('<a class="btn small" href="/worktime/history?page=%s">Następna →</a>'%(page+1))
        out.append('</div>')
        self._dev3_html('Historia korekt',''.join(out),'worktime')

    def dev4_vault_change(self,file_id,kind,fields):
        app=self._dev3_app();user=self._dev3_me()
        from rk_dev5_vault import vault_change_safe
        if kind=='delete' and fields.get('confirmation')!='USUŃ':
            raise ValueError('Wpisz USUŃ, aby usunąć dokument sejfu')
        vault_change_safe(app.db,app.FILES_DIR,file_id,user['id'],user['role']=='admin',kind,
                          fields.get('old_passphrase',''),fields.get('new_passphrase',''))
        self.redirect('/vault')
