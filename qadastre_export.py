# -*- coding: utf-8 -*-
"""
/***************************************************************************
 Qadastre - Export method class
                                                                 A QGIS plugin
 This plugins helps users to import the french land registry ('cadastre')
 into a database. It is meant to ease the use of the data in QGIs
 by providing search tools and appropriate layer symbology.
                                                            -------------------
                begin                                : 2013-06-11
                copyright                        : (C) 2013 by 3liz
                email                                : info@3liz.com
 ***************************************************************************/

/***************************************************************************
 *                                                                                                                                                 *
 *     This program is free software; you can redistribute it and/or modify    *
 *     it under the terms of the GNU General Public License as published by    *
 *     the Free Software Foundation; either version 2 of the License, or         *
 *     (at your option) any later version.                                                                     *
 *                                                                                                                                                 *
 ***************************************************************************/
"""

import csv
import os.path
import operator
import re
import tempfile
from PyQt4.QtCore import *
from PyQt4.QtGui import *
from qgis.core import *


class qadastreExport(QObject):

    def __init__(self, dialog, etype='proprietaire', feat=None):
        self.dialog = dialog

        self.etype = etype
        self.feat = feat

        # label for header2
        if self.etype == 'proprietaire':
            self.typeLabel = u'DE PROPRIÉTÉ'
        else:
            self.typeLabel = u'PARCELLAIRE'

        # Sql filters
        self.sqlFilters = {}
        if feat.has_key('geo_parcelle'):
            self.sqlFilters['geo_parcelle'] = u" AND geo_parcelle = '%s'" % feat['geo_parcelle']
        if feat.has_key('comptecommunal'):
            self.sqlFilters['comptecommunal'] = u" AND comptecommunal = '%s'" % feat['comptecommunal']

        # List of templates
        self.composerTemplates = [
            {
                'key': 'header1',
                'names': ['annee', 'ccodep', 'ccodir', 'ccocom', 'libcom'],
                'type': 'sql',
                'filter': 'comptecommunal'
            },
            {
                'key': 'header2',
                'names': ['type'],
                'type': 'properties',
                'source': [self.typeLabel]
            },
            {
                'key': 'header3',
                'names': ['comptecommunal'],
                'type': 'properties',
                'source': ['uncomtecommunal']
            },
            {
                'key': 'proprietaires',
                'names': ['proprietaires'],
                'type': 'sql',
                'filter': 'comptecommunal'
            },
            {
                'key': 'proprietes_baties_line',
                'names': ['section', 'ndeplan', 'ndevoirie', 'adresse', 'coderivoli', 'bat', 'ent', 'niv', 'ndeporte', 'numeroinvar', 'star', 'meval', 'af', 'natloc', 'cat', 'revenucadastral', 'coll', 'natexo', 'anret', 'andeb', 'fractionrcexo', 'pourcentageexo', 'txom', 'coefreduc'],
                'type': 'sql',
                'filter': 'comptecommunal'
            },
            {
                'key': 'proprietes_baties',
                'names': ['lines'],
                'type': 'parent',
                'source': [4]
            },
            {
                'key': 'proprietes_non_baties_line',
                'names': ['section', 'ndeplan', 'ndevoirie', 'adresse', 'coderivoli', 'nparcprim', 'fpdp', 'star', 'suf', 'grssgr', 'cl', 'natcult', 'contenance', 'revenucadastral', 'coll', 'natexo', 'anret', 'fractionrcexo', 'pourcentageexo', 'tc', 'lff'],
                'type': 'sql'
            },
            {
                'key': 'proprietes_non_baties',
                'names': ['lines'],
                'type': 'parent',
                'source': [6]
            }
        ]

        # common qadastre methods
        self.qc = self.dialog.qc


    def exportAsPDF(self):
        '''
        Export as PDF using the template composer
        filled with appropriate data
        '''

        # For each composer element
        # get template and set data
        index=0
        for item in self.composerTemplates:
            self.assignDataToTemplate(index, item)
            index+=1

        # Load the composer from template
        # and replace data inside it
        qgisReplaceDict = {}
        for item in self.composerTemplates:
            qgisReplaceDict[item['key']] = item['content']
        composition = self.loadComposerFromTemplate(qgisReplaceDict)

        # Export as pdf
        if composition:
            composition.exportAsPDF('/tmp/test.pdf')


    def assignDataToTemplate(self, index, item):
        '''
        Take content from template file
        corresponding to the key
        and assign data from item
        '''
        content = ''
        replaceDict = ''
        # Build template file path
        tplPath = os.path.join(
            self.qc.plugin_dir,
            "templates/%s.tpl" % item['key']
        )

        # Build replace dict depending on source type
        if item['type'] == 'sql':
            # Get sql file
            fin = open(tplPath + '.sql')
            sql = fin.read().decode('utf-8')
            fin.close()
            # Add schema to search_path if postgis
            if self.dialog.dbType == 'postgis':
                sql = self.qc.setSearchPath(sql, self.dialog.schema)
            # Add where clause depending on etype
            #~ if self.etype == 'proprietaire':
                #~ sql+= " AND p.comptecommunal = '201280*00461'"
            # Run SQL
            [header, data, rowCount] = self.qc.fetchDataFromSqlQuery(self.dialog.connector, sql)

            # Build dict
            for line in data:
                replaceDict = {}
                for i in range(len(item['names'])):
                    replaceDict['$%s' % item['names'][i] ] = u'%s' % line[i]
                content+= self.getHtmlFromTemplate(tplPath, replaceDict)

        elif item['type'] == 'properties':
            # build replace dict from properties
            replaceDict = {}
            for i in range(len(item['names'])):
                replaceDict['$' + item['names'][i]] = item['source'][i]
            content = self.getHtmlFromTemplate(tplPath, replaceDict)

        elif item['type'] == 'parent':
            replaceDict = {}
            for i in range(len(item['names'])):
                replaceDict['$' + item['names'][i]] = self.composerTemplates[ item['source'][i] ]['content']
            content = self.getHtmlFromTemplate(tplPath, replaceDict)

        self.composerTemplates[index]['content'] = content


    def getHtmlFromTemplate(self, tplPath, replaceDict):
        '''
        Get the content of a template file
        and replace all variables with given data
        '''
        QApplication.setOverrideCursor(Qt.WaitCursor)

        def replfunc(match):
            return replaceDict[match.group(0)]
        regex = re.compile('|'.join(re.escape(x) for x in replaceDict))

        try:
            fin = open(tplPath)
            data = fin.read().decode('utf-8')
            fin.close()
            data = regex.sub(replfunc, data)
            return data

        except IOError, e:
            msg = u"Erreur lors de l'export: %s" % e
            self.go = False
            self.qc.updateLog(msg)
            return msg

        finally:
            QApplication.restoreOverrideCursor()

    def loadComposerFromTemplate(self, replaceDict):
        '''
        Load the template composer
        '''
        # Get composer template
        from PyQt4 import QtXml
        d = QtXml.QDomDocument()
        template = file("/home/kimaidou/.qgis2/python/plugins/Qadastre/composers/releve.qpt").read()
        d.setContent(template)

        # Get composition
        composition = QgsComposition(QgsMapRenderer())
        composition.loadFromTemplate(d, replaceDict)

        return composition