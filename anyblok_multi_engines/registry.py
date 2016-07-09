# This file is a part of the AnyBlok Multi Engines project
#
#    Copyright (C) 2016 Jean-Sebastien SUZANNE <jssuzanne@anybox.fr>
#
# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file,You can
# obtain one at http://mozilla.org/MPL/2.0/.
from anyblok.registry import Registry, RegistryException, RegistryManager
from anyblok.config import Configuration
from sqlalchemy.orm import sessionmaker, scoped_session
from anyblok.environment import EnvironmentManager
from .config import get_url
from sqlalchemy import create_engine
from random import choice


class MixinSession:

    def get_bind(self, mapper=None, clause=None):
        if self.registry.session_connection:
            return self.registry.session_connection
        elif self.registry.unittest_transaction:
            return self.registry.bind
        elif self._flushing:
            return self.registry.get_engine_for(ro=False)
        else:
            return self.registry.get_engine_for()


class MultiEngines:

    def init_engine(self, db_name=None):
        kwargs = self.init_engine_options()
        gurl = Configuration.get('get_url', get_url)
        self.engines = {'ro': [], 'wo': []}
        url = Configuration.get('db_url')
        self._engine = None
        if url:
            url = gurl(db_name=db_name, url=url)
            engine = create_engine(url, **kwargs)
            self.engines['wo'].append(engine)
            self.engines['ro'].append(engine)

        for url in Configuration.get('db_ro_url', []) or []:
            url = gurl(db_name=db_name, url=url)
            engine = create_engine(url, **kwargs)
            self.engines['ro'].append(engine)

        for url in Configuration.get('db_wo_url', []) or []:
            url = gurl(db_name=db_name, url=url)
            engine = create_engine(url, **kwargs)
            self.engines['wo'].append(engine)

        if not self.engines['ro'] and not self.engines['wo']:
            url = gurl(db_name=db_name)
            engine = create_engine(url, **kwargs)
            self.engines['wo'].append(engine)
            self.engines['ro'].append(engine)
        elif not self.engines['wo']:
            self.loadwithoutmigration = True

    def get_engine_for(self, ro=True):
        engines = self.engines['ro'] if ro else self.engines['wo']
        if not engines:
            raise RegistryException("No engine found for do action %r" % (
                "read" if ro else "write"))

        return choice(engines)

    def init_bind(self):
        self._bind = None
        self.unittest_transaction = None
        if self.unittest:
            self.unittest_bind = self.engine.connect()
            self.unittest_transaction = self.bind.begin()

    @property
    def bind(self):
        if not self._bind:
            if self.unittest:
                self._bind = self.unittest_bind
            else:
                self._bind = self.engine

        return self._bind

    @property
    def engine(self):
        if not self._engine:
            self._engine = self.get_engine_for(ro=self.loadwithoutmigration)

        return self._engine

    def create_session_factory(self):
        if self.Session is None or self.must_recreate_session_factory():
            query_bases = [] + self.loaded_cores['Query']
            query_bases += [self.registry_base]
            Query = type('Query', tuple(query_bases), {})
            session_bases = [self.registry_base, MixinSession]
            session_bases.extend(self.loaded_cores['Session'])
            Session = type('Session', tuple(session_bases), {
                'registry_query': Query})

            self.session_connection = None
            if self.Session:
                self.session_connection = self.connection()

            extension = self.additional_setting.get('sa.session.extension')
            if extension:
                extension = extension()

            self.Session = scoped_session(
                sessionmaker(class_=Session, extension=extension),
                EnvironmentManager.scoped_function_for_session())
            self.nb_query_bases = len(self.loaded_cores['Query'])
            self.nb_session_bases = len(self.loaded_cores['Session'])
        else:
            self.flush()

    def commit(self, *args, **kwargs):
        super(MultiEngines, self).commit(*args, **kwargs)
        self.session_connection = None

    def close(self):
        self.close_session()
        for engine in set(self.engines['ro'] + self.engines['wo']):
            engine.dispose()

        if self.db_name in RegistryManager.registries:
            del RegistryManager.registries[self.db_name]


class RegistryMultiEngines(MultiEngines, Registry):
    pass