# -*- encoding: utf-8 -*-
###############################################################################
#                                                                             #
# Copyright (C) 2013  Renato Lima - Akretion                                  #
#                                                                             #
#This program is free software: you can redistribute it and/or modify         #
#it under the terms of the GNU Affero General Public License as published by  #
#the Free Software Foundation, either version 3 of the License, or            #
#(at your option) any later version.                                          #
#                                                                             #
#This program is distributed in the hope that it will be useful,              #
#but WITHOUT ANY WARRANTY; without even the implied warranty of               #
#MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the                #
#GNU Affero General Public License for more details.                          #
#                                                                             #
#You should have received a copy of the GNU Affero General Public License     #
#along with this program.  If not, see <http://www.gnu.org/licenses/>.        #
###############################################################################

import re
import string
from datetime import datetime
import tempfile

from openerp import pooler
from openerp.osv import orm
from openerp.tools.translate import _
from openerp.addons.l10n_br_account.sped.document import FiscalDocument
import pysped
from pysped.nfe.leiaute.consrecinfe_310 import ProtNFe


class NFe200(FiscalDocument):

    def __init__(self):
        super(NFe200, self).__init__()
        self.nfe = None
        self.nfref = None
        self.det = None
        self.dup = None

    def _serializer(self, cr, uid, ids, nfe_environment, context=None):

        pool = pooler.get_pool(cr.dbname)
        nfes = []

        if not context:
            context = {'lang': 'pt_BR'}

        for inv in pool.get('account.invoice').browse(cr, uid, ids, context):

            company = pool.get('res.partner').browse(
                cr, uid, inv.company_id.partner_id.id, context)

            self.nfe = self.get_NFe()
            
            self._nfe_identification(
                cr, uid, ids, inv, company, nfe_environment, context)

            self._in_out_adress(cr, uid, ids, inv, context)

            for inv_related in inv.fiscal_document_related_ids:
                self.nfref = self._get_NFRef()
                self._nfe_references(cr, uid, ids, inv_related)
                self.nfe.infNFe.ide.NFref.append(self.nfref)

            self._emmiter(cr, uid, ids, inv, company, context)
            self._receiver(cr, uid, ids, inv, company, nfe_environment, context)

            i = 0
            for inv_line in inv.invoice_line:
                i += 1
                self.det = self._get_Det()
                self._details(cr, uid, ids, inv, inv_line, i, context)

                for inv_di in inv_line.import_declaration_ids:

                    self.di = self._get_DI()
                    self._di(cr, uid, ids, inv, inv_line, inv_di, i, context)
                    self.det.prod.DI.append(self.di)
                    self.di = self._get_DI()

                    for inv_di_line in inv_di.line_ids:
                        self.di_line = self._get_Addition()
                        self._adiction(cr, uid, ids, inv, inv_line, inv_di, inv_di_line, i, context)
                        self.di.adi.append(self.di_line)

                self.nfe.infNFe.det.append(self.det)

            if inv.journal_id.revenue_expense:
                for line in inv.move_line_receivable_id:
                    self.dup = self._get_Dup()
                    self._encashment_data(cr, uid, ids, inv, line, context)
                    self.nfe.infNFe.cobr.dup.append(self.dup)

            try:
                self._carrier_data(cr, uid, ids, inv, context)
            except AttributeError:
                pass

            self.vol = self._get_Vol()
            self._weight_data(cr, uid, ids, inv, context=None)
            self.nfe.infNFe.transp.vol.append(self.vol)

            self._additional_information(cr, uid, ids, inv, context)
            self._total(cr, uid, ids, inv, context)

            # Gera Chave da NFe
            self.nfe.gera_nova_chave()
            nfes.append(self.nfe)

        return nfes
    
    def _deserializer(self, cr, uid, nfe, context):
        if not context:
            context = {'lang': 'pt_BR'}
        if nfe.infNFe.ide.tpNF.valor == 0:
            action = ('account', 'action_invoice_tree1')
        elif nfe.infNFe.ide.tpNF.valor == 1:
            action = ('account', 'action_invoice_tree2')

        self.nfe = nfe
        #TODO Buscar o protocolo da nota 
        self.protNFe = ProtNFe()
        nfref = self._get_NFRef()
        nfref.xml = nfe.xml
        self.nfref = nfref

        self.dup = self._get_Dup()
        self.dup.xml = nfe.xml

        pool = pooler.get_pool(cr.dbname)
        invoice_obj = pool.get('account.invoice')

        try:
            nfe_references = self._get_nfe_references(
                cr, uid, pool, context=context)
            fiscal_doc_obj = pool.get('l10n_br_account_product.document.related')
            fiscal_doc_id = fiscal_doc_obj.create(cr, uid, nfe_references)
        except AttributeError:
            pass

        invoice_vals = {            
        }

        carrier_data = self._get_carrier_data(cr, uid, pool, context=context)
        in_out_data = self._get_in_out_adress(cr, uid, pool, context=context)
        receiver = self._get_receiver(cr, uid, pool, context=context)
        nfe_identification = self._get_nfe_identification(
            cr, uid, pool, context=context)

        emmiter = self._get_emmiter(cr, uid, pool, context=context)
        encashment_data = self._get_encashment_data(
            cr, uid, pool, context=context)
        
        adittional = self._get_additional_information(cr, uid, pool, context=context)
        weight_data = self._get_weight_data(cr, uid, pool, context=context)
        protocol = self._get_protocol(cr, uid, pool, context=context)

        invoice_vals.update(carrier_data)
        invoice_vals.update(in_out_data)
        invoice_vals.update(receiver)
        invoice_vals.update(nfe_identification)
        invoice_vals.update(emmiter)
        invoice_vals.update(encashment_data)
        invoice_vals.update(adittional)
        invoice_vals.update(weight_data)

        inv_line_ids = []
        for det in self.nfe.infNFe.det:
            self.det = det
            inv_line_ids += self._get_details(cr, uid, pool, context=context)

        invoice_vals['invoice_line'] = inv_line_ids        

        return invoice_vals, action



    def _nfe_identification(self, cr, uid, ids, inv, company, nfe_environment, context=None):

        # Identificação da NF-e
        #
        self.nfe.infNFe.ide.cUF.valor = company.state_id and company.state_id.ibge_code or ''
        self.nfe.infNFe.ide.cNF.valor = ''
        self.nfe.infNFe.ide.natOp.valor = inv.cfop_ids[0].small_name or ''
        self.nfe.infNFe.ide.indPag.valor = inv.payment_term and inv.payment_term.indPag or '0'
        self.nfe.infNFe.ide.mod.valor  = inv.fiscal_document_id.code or ''
        self.nfe.infNFe.ide.serie.valor = inv.document_serie_id.code or ''
        self.nfe.infNFe.ide.nNF.valor = inv.internal_number or ''
        self.nfe.infNFe.ide.dEmi.valor = inv.date_invoice or ''
        self.nfe.infNFe.ide.dSaiEnt.valor = datetime.strptime(inv.date_in_out, '%Y-%m-%d %H:%M:%S').date() or ''
        self.nfe.infNFe.ide.cMunFG.valor = ('%s%s') % (company.state_id.ibge_code, company.l10n_br_city_id.ibge_code)
        self.nfe.infNFe.ide.tpImp.valor = 1  # (1 - Retrato; 2 - Paisagem)
        self.nfe.infNFe.ide.tpEmis.valor = 1
        self.nfe.infNFe.ide.tpAmb.valor = nfe_environment
        self.nfe.infNFe.ide.finNFe.valor = inv.nfe_purpose
        self.nfe.infNFe.ide.procEmi.valor = 0
        self.nfe.infNFe.ide.verProc.valor = 'OpenERP Brasil v7'

        if inv.cfop_ids[0].type in ("input"):
            self.nfe.infNFe.ide.tpNF.valor = '0'
        else:
            self.nfe.infNFe.ide.tpNF.valor = '1'
    
    def _get_nfe_identification(self, cr, uid, pool, context=None):

        # Identificação da NF-e
        #
        res = {}

        fiscal_doc_ids = pool.get('l10n_br_account.fiscal.document').search(
            cr, uid, [('code', '=', self.nfe.infNFe.ide.mod.valor)])

        res['fiscal_document_id'] = \
            fiscal_doc_ids[0] if fiscal_doc_ids else False

        document_serie_ids = pool.get('l10n_br_account.document.serie').search(
            cr, uid, [('code', '=', self.nfe.infNFe.ide.serie.valor),
                      ('fiscal_document_id', '=', fiscal_doc_ids[0]) ])

        res['document_serie_id'] = \
            document_serie_ids[0] if document_serie_ids else False
        res['number'] = self.nfe.infNFe.ide.nNF.valor
        res['internal_number'] = self.nfe.infNFe.ide.nNF.valor
        res['date_invoice'] = self.nfe.infNFe.ide.dEmi.valor
        res['date_in_out'] = self.nfe.infNFe.ide.dSaiEnt.valor
        res['nfe_purpose'] = str(self.nfe.infNFe.ide.finNFe.valor)
        res['nfe_access_key'] = self.nfe.infNFe.Id.valor

        #if self.nfe.infNFe.ide.tpNF.valor == 0:
        res['type'] = 'in_invoice' #Fixo por hora - apenas nota de entrada
        #else:
        #    res['type'] = 'out_invoice'

        # TODO: Campo importante para o SPED
        # self.nfe.infNFe.ide.indPag.valor =
        # inv.payment_term and inv.payment_term.indPag or '0'
        # TODO: Adicionar campo nfe_enviroment na invoice assim como foi feito
        # TODO: com a versão da nfe
        # self.nfe.infNFe.ide.tpAmb.valor = nfe_environment

        return res


    def _in_out_adress(self, cr, uid, ids, inv, context=None):

        #
        # Endereço de Entrega ou Retirada
        #
        if inv.partner_shipping_id:
            if inv.partner_id.id != inv.partner_shipping_id.id:
                if self.nfe.infNFe.ide.tpNF.valor == '0':
                    self.nfe.infNFe.retirada.CNPJ.valor = re.sub('[%s]' % re.escape(string.punctuation), '', inv.partner_shipping_id.cnpj_cpf or '')
                    self.nfe.infNFe.retirada.xLgr.valor = inv.partner_shipping_id.street or ''
                    self.nfe.infNFe.retirada.nro.valor = inv.partner_shipping_id.number or ''
                    self.nfe.infNFe.retirada.xCpl.valor = inv.partner_shipping_id.street2 or ''
                    self.nfe.infNFe.retirada.xBairro.valor = inv.partner_shipping_id.district or 'Sem Bairro'
                    self.nfe.infNFe.retirada.cMun.valor = '%s%s' % (inv.partner_shipping_id.state_id.ibge_code, inv.partner_shipping_id.l10n_br_city_id.ibge_code)
                    self.nfe.infNFe.retirada.xMun.valor = inv.partner_shipping_id.l10n_br_city_id.name or ''
                    self.nfe.infNFe.retirada.UF.valor = inv.partner_shipping_id.state_id.code or ''
                else:
                    self.nfe.infNFe.entrega.CNPJ.valor = re.sub('[%s]' % re.escape(string.punctuation), '', inv.partner_shipping_id.cnpj_cpf or '')
                    self.nfe.infNFe.entrega.xLgr.valor = inv.partner_shipping_id.street or ''
                    self.nfe.infNFe.entrega.nro.valor = inv.partner_shipping_id.number or ''
                    self.nfe.infNFe.entrega.xCpl.valor = inv.partner_shipping_id.street2 or ''
                    self.nfe.infNFe.entrega.xBairro.valor = inv.partner_shipping_id.district or 'Sem Bairro'
                    self.nfe.infNFe.entrega.cMun.valor = '%s%s' % (inv.partner_shipping_id.state_id.ibge_code, inv.partner_shipping_id.l10n_br_city_id.ibge_code)
                    self.nfe.infNFe.entrega.xMun.valor = inv.partner_shipping_id.l10n_br_city_id.name or ''
                    self.nfe.infNFe.entrega.UF.valor = inv.partner_shipping_id.state_id.code or ''

    def _get_in_out_adress(self, cr, uid, pool, context=None):

        if self.nfe.infNFe.ide.tpNF.valor == '0':
            cnpj = self._mask_cnpj_cpf(True, self.nfe.infNFe.retirada.CNPJ.valor)
        else:
            print self.nfe.infNFe.entrega.CNPJ.valor
            cnpj = self._mask_cnpj_cpf(True, self.nfe.infNFe.entrega.CNPJ.valor)

        partner_ids = pool.get('res.partner').search(
            cr, uid, [('cnpj_cpf', '=', cnpj)])

        return {'partner_shipping_id': partner_ids[0] if partner_ids else False}

    def _nfe_references(self, cr, uid, ids, inv_related, context=None):

        #
        # Documentos referenciadas
        #

        if inv_related.document_type == 'nf':
            self.nfref.refNF.cUF.valor = inv_related.state_id and inv_related.state_id.ibge_code or '',
            self.nfref.refNF.AAMM.valor = datetime.strptime(inv_related.date, '%Y-%m-%d').strftime('%y%m') or ''
            self.nfref.refNF.CNPJ.valor = re.sub('[%s]' % re.escape(string.punctuation), '', inv_related.cnpj_cpf or '')
            self.nfref.refNF.mod.valor = inv_related.fiscal_document_id and inv_related.fiscal_document_id.code or ''
            self.nfref.refNF.serie.valor = inv_related.serie or ''
            self.nfref.refNF.nNF.valor = inv_related.internal_number or ''

        elif inv_related.document_type == 'nfrural':
            self.nfref.refNFP.cUF.valor = inv_related.state_id and inv_related.state_id.ibge_code or '',
            self.nfref.refNFP.AAMM.valor = datetime.strptime(inv_related.date, '%Y-%m-%d').strftime('%y%m') or ''
            self.nfref.refNFP.IE.valor = re.sub('[%s]' % re.escape(string.punctuation), '', inv_related.inscr_est or '')
            self.nfref.refNFP.mod.valor = inv_related.fiscal_document_id and inv_related.fiscal_document_id.code or ''
            self.nfref.refNFP.serie.valor = inv_related.serie or ''
            self.nfref.refNFP.nNF.valor = inv_related.internal_number or ''

            if inv_related.cpfcnpj_type == 'cnpj':
                self.nfref.refNFP.CNPJ.valor = re.sub('[%s]' % re.escape(string.punctuation), '', inv_related.cnpj_cpf or '')
            else:
                self.nfref.refNFP.CPF.valor = re.sub('[%s]' % re.escape(string.punctuation), '', inv_related.cnpj_cpf or '')

        elif inv_related.document_type == 'nfe':
            self.nfref.refNFe.valor = inv_related.access_key or ''

        elif inv_related.document_type == 'cte':
            self.nfref.refCTe.valor = inv_related.access_key or ''

        elif inv_related.document_type == 'cf':
            self.nfref.refECF.mod.valor = inv_related.fiscal_document_id and inv_related.fiscal_document_id.code or ''
            self.nfref.refECF.nECF.valor = inv_related.internal_number
            self.nfref.refECF.nCOO.valor = inv_related.serie

    def _get_nfe_references(self, cr, uid, pool, context=None):

        #
        # Documentos referenciadas
        #
        nfe_reference = {}
        state_obj = pool.get('res.country.state')
        fiscal_doc_obj = pool.get('l10n_br_account_product.document.related')

        if self.nfref.refNF.CNPJ.valor:

            state_ids = state_obj.search(cr, uid, [
                ('ibge_code', '=', self.nfref.refNF.cUF.valor)])

            fiscal_doc_ids = fiscal_doc_obj.search(cr, uid, [
                ('code', '=', self.nfref.refNF.mod.valor)])

            nfe_reference.update({
                'document_type': 'nf',
                'state_id': state_ids[0] if state_ids else False,
                'date': self.nfref.refNF.AAMM.valor or False,
                'cnpj_cpf': self._mask_cnpj_cpf(True, self.nfref.refNF.CNPJ.valor) or False,
                'fiscal_document_id': fiscal_doc_ids[0] if fiscal_doc_ids
                else False,
                'serie': self.nfref.refNF.serie.valor or False,
                'internal_number': self.nfref.refNF.nNF.valor or False,
            })

        elif self.nfref.refNFP.CNPJ.valor:

            state_ids = state_obj.search(cr, uid, [
                ('ibge_code', '=', self.nfref.refNFP.cUF.valor)])
            fiscal_doc_ids = fiscal_doc_obj.search(cr, uid, [
                ('code', '=', self.nfref.refNFP.mod.valor)])

            cnpj = self._mask_cnpj_cpf(True, self.nfref.refNFP.CNPJ.valor)
            cpf = self._mask_cnpj_cpf(False, self.nfref.refNFP.CPF.valor)
            cnpj_cpf = (cnpj or cpf)

            nfe_reference.update({
                'document_type': 'nfrural',
                'state_id': state_ids[0] if state_ids else False,
                'date': self.nfref.refNFP.AAMM.valor,
                'inscr_est': self.nfref.refNFP.IE.valor,
                'fiscal_document_id': fiscal_doc_ids[0] if fiscal_doc_ids
                else False,
                'serie': self.nfref.refNFP.serie.valor,
                'internal_number': self.nfref.refNFP.nNF.valor,
                'cnpj_cpf': cnpj_cpf,
            })
        elif self.nfref.refNFe.valor:
            nfe_reference.update({
                'document_type': 'nfe',
                'access_key': self.nfref.refNFe.valor,
            })
        elif self.nfref.refCTe.valor:
            nfe_reference.update({
                'document_type': 'cte',
                'access_key': self.nfref.refCTe.valor,
            })
        elif self.nfref.refECF:
            fiscal_document_ids = \
                pool.get('l10n_br_account.fiscal.document').search(
                    cr, uid, [('code', '=', self.nfref.refECF.mod.valor)])

            nfe_reference.update({
                'document_type': 'cf',
                'fiscal_document_id': fiscal_document_ids[0] if
                fiscal_document_ids else False,
                'serie': self.nfref.refNF.serie.valor,
                'internal_number': self.nfref.refNF.nNF.valor,
            })

        return nfe_reference



    def _emmiter(self, cr, uid, ids, inv, company, context=None):

        #
        # Emitente
        #
        self.nfe.infNFe.emit.CNPJ.valor = re.sub('[%s]' % re.escape(string.punctuation), '', inv.company_id.partner_id.cnpj_cpf or '')
        self.nfe.infNFe.emit.xNome.valor = inv.company_id.partner_id.legal_name[:60]
        self.nfe.infNFe.emit.xFant.valor = inv.company_id.partner_id.name
        self.nfe.infNFe.emit.enderEmit.xLgr.valor = company.street or ''
        self.nfe.infNFe.emit.enderEmit.nro.valor = company.number or ''
        self.nfe.infNFe.emit.enderEmit.xCpl.valor = company.street2 or ''
        self.nfe.infNFe.emit.enderEmit.xBairro.valor = company.district or 'Sem Bairro'
        self.nfe.infNFe.emit.enderEmit.cMun.valor = '%s%s' % (company.state_id.ibge_code, company.l10n_br_city_id.ibge_code)
        self.nfe.infNFe.emit.enderEmit.xMun.valor = company.l10n_br_city_id.name or ''
        self.nfe.infNFe.emit.enderEmit.UF.valor = company.state_id.code or ''
        self.nfe.infNFe.emit.enderEmit.CEP.valor = re.sub('[%s]' % re.escape(string.punctuation), '', str(company.zip or '').replace(' ',''))
        self.nfe.infNFe.emit.enderEmit.cPais.valor = company.country_id.bc_code[1:]
        self.nfe.infNFe.emit.enderEmit.xPais.valor = company.country_id.name
        self.nfe.infNFe.emit.enderEmit.fone.valor = re.sub('[%s]' % re.escape(string.punctuation), '', str(company.phone or '').replace(' ',''))
        self.nfe.infNFe.emit.IE.valor = re.sub('[%s]' % re.escape(string.punctuation), '', inv.company_id.partner_id.inscr_est or '')
        self.nfe.infNFe.emit.IEST.valor = ''
        self.nfe.infNFe.emit.IM.valor = re.sub('[%s]' % re.escape(string.punctuation), '', inv.company_id.partner_id.inscr_mun or '')
        self.nfe.infNFe.emit.CRT.valor = inv.company_id.fiscal_type or ''

        if inv.company_id.partner_id.inscr_mun:
            self.nfe.infNFe.emit.CNAE.valor = re.sub('[%s]' % re.escape(string.punctuation), '', inv.company_id.cnae_main_id.code or '')

    def _get_emmiter(self, cr, uid, pool, context=None):
        #
        # Emitente da nota é o fornecedor
        #
        emitter = {}

        cnpj_cpf = ''

        if self.nfe.infNFe.emit.CNPJ.valor:
            cnpj_cpf = self._mask_cnpj_cpf(True, self.nfe.infNFe.emit.CNPJ.valor)

        elif self.nfe.infNFe.emit.CPF.valor:
            cnpj_cpf = self._mask_cnpj_cpf(False,
                                           self.nfe.infNFe.emit.CPF.valor)

        receiver_partner_ids = pool.get('res.partner').search(
            cr, uid, [('cnpj_cpf', '=', cnpj_cpf)])

        # Quando o cliente é estrangeiro, ele nao possui cnpj. Por isso
        # realizamos a busca usando como chave de busca o nome da empresa ou
        # a sua razao social
        if not receiver_partner_ids:
            aux = ['|',
                   ('legal_name', '=', self.nfe.infNFe.emit.xNome.valor),
                   ('legal_name', '=', self.nfe.infNFe.emit.xNome.valor)]
            receiver_partner_ids = pool.get('res.partner').search(
                cr, uid, aux)

        if len(receiver_partner_ids) > 0:
            emitter['partner_id'] = receiver_partner_ids[0]
            partner =  pool.get('res.partner').browse(cr, uid, receiver_partner_ids[0])
            #Busca conta de pagamento do fornecedor
            emitter['account_id'] = partner.property_account_payable.id
        else: #Retorna os dados para cadastro posteriormente
            partner = {}
            
            partner['is_company'] = True
            partner['name'] = self.nfe.infNFe.emit.xNome.valor
            partner['legal_name'] = self.nfe.infNFe.emit.xFant.valor
            partner['cnpj_cpf'] = self.nfe.infNFe.emit.CNPJ.valor
            partner['inscr_est'] = self.nfe.infNFe.emit.IE.valor
            partner['inscr_mun'] = self.nfe.infNFe.emit.IM.valor
            partner['zip'] = self.nfe.infNFe.emit.enderEmit.CEP.valor
            partner['street'] = self.nfe.infNFe.emit.enderEmit.xLgr.valor
            partner['street2'] = self.nfe.infNFe.emit.enderEmit.xCpl.valor
            partner['district'] = self.nfe.infNFe.emit.enderEmit.xBairro.valor
            partner['number'] = self.nfe.infNFe.emit.enderEmit.nro.valor            
            
            city_id = pool.get('l10n_br_base.city').search(
                cr, uid, [('ibge_code', '=', str(self.nfe.infNFe.emit.enderEmit.cMun.valor)[2:])])
            if len(city_id) > 0:     
                city = pool.get('l10n_br_base.city').browse(cr, uid, city_id[0])
                partner['l10n_br_city_id'] = city_id[0]
                partner['state_id'] = city.state_id.id
                partner['country_id'] = city.state_id.country_id.id
                
            partner['phone'] = self.nfe.infNFe.emit.enderEmit.fone.valor
            partner['supplier'] = True
            
            emitter['partner_id'] = False
            emitter['partner_values'] = partner
            emitter['account_id'] = False
                    
        return emitter

    def _receiver(self, cr, uid, ids, inv, company, nfe_environment, context=None):

        #
        # Destinatário
        #
        partner_bc_code = ''
        address_invoice_state_code = ''
        address_invoice_city = ''
        partner_cep = ''

        if inv.partner_id.country_id.bc_code:
            partner_bc_code = inv.partner_id.country_id.bc_code[1:]

        if inv.partner_id.country_id.id != company.country_id.id:
            address_invoice_state_code = 'EX'
            address_invoice_city = 'Exterior'
            partner_cep = ''
        else:
            address_invoice_state_code = inv.partner_id.state_id.code
            address_invoice_city = inv.partner_id.l10n_br_city_id.name or ''
            partner_cep = re.sub('[%s]' % re.escape(string.punctuation), '', str(inv.partner_id.zip or '').replace(' ',''))

        # Se o ambiente for de teste deve ser
        # escrito na razão do destinatário
        if nfe_environment == '2':
            self.nfe.infNFe.dest.xNome.valor = 'NF-E EMITIDA EM AMBIENTE DE HOMOLOGACAO - SEM VALOR FISCAL'
        else:
            self.nfe.infNFe.dest.xNome.valor = inv.partner_id.legal_name[:60] or ''

        if inv.partner_id.is_company:
            self.nfe.infNFe.dest.CNPJ.valor = re.sub('[%s]' % re.escape(string.punctuation), '', inv.partner_id.cnpj_cpf or '')
            self.nfe.infNFe.dest.IE.valor = re.sub('[%s]' % re.escape(string.punctuation), '', inv.partner_id.inscr_est or '')
        else:
            self.nfe.infNFe.dest.CPF.valor = re.sub('[%s]' % re.escape(string.punctuation), '', inv.partner_id.cnpj_cpf or '')

        self.nfe.infNFe.dest.enderDest.xLgr.valor = inv.partner_id.street or ''
        self.nfe.infNFe.dest.enderDest.nro.valor = inv.partner_id.number or ''
        self.nfe.infNFe.dest.enderDest.xCpl.valor = inv.partner_id.street2 or ''
        self.nfe.infNFe.dest.enderDest.xBairro.valor = inv.partner_id.district or 'Sem Bairro'
        self.nfe.infNFe.dest.enderDest.cMun.valor = '%s%s' % (inv.partner_id.state_id.ibge_code, inv.partner_id.l10n_br_city_id.ibge_code)
        self.nfe.infNFe.dest.enderDest.xMun.valor = address_invoice_city
        self.nfe.infNFe.dest.enderDest.UF.valor = address_invoice_state_code
        self.nfe.infNFe.dest.enderDest.CEP.valor = partner_cep
        self.nfe.infNFe.dest.enderDest.cPais.valor = partner_bc_code
        self.nfe.infNFe.dest.enderDest.xPais.valor = inv.partner_id.country_id.name or ''
        self.nfe.infNFe.dest.enderDest.fone.valor = re.sub('[%s]' % re.escape(string.punctuation), '', str(inv.partner_id.phone or '').replace(' ',''))
        self.nfe.infNFe.dest.email.valor = inv.partner_id.email or ''

    def _get_receiver(self, cr, uid, pool, context=None):
        #
        # Recebedor da mercadoria é a empresa
        #
        receiver = {}
        partner_obj = pool.get('res.partner')
        company_obj = pool.get('res.company')
        cnpj = self._mask_cnpj_cpf(True, self.nfe.infNFe.dest.CNPJ.valor)

        emitter_partner_ids = partner_obj.search(
            cr, uid, [('cnpj_cpf', '=', cnpj)])
        
        if len(emitter_partner_ids) > 0:
            company_ids = company_obj.search(
                cr, uid, [('partner_id', '=', emitter_partner_ids[0])])
            if len(company_ids) > 0:                        
                receiver['company_id'] = company_ids[0]
                return receiver
        
        raise Exception('O xml a ser importado foi emitido para o CNPJ {0} - {1}\n'\
                        'o qual não corresponde ao CNPJ cadastrado na empresa\n'\
                        'O arquivo não será importado.'.format(cnpj, self.nfe.infNFe.dest.xNome.valor))


    def _details(self, cr, uid, ids, inv, inv_line, i, context=None):

        #
        # Detalhe
        #

        self.det.nItem.valor = i
        self.det.prod.cProd.valor = inv_line.product_id.code or ''
        self.det.prod.cEAN.valor = inv_line.product_id.ean13 or ''
        self.det.prod.xProd.valor = inv_line.product_id.name[:120] or ''
        self.det.prod.NCM.valor = re.sub('[%s]' % re.escape(string.punctuation), '', inv_line.fiscal_classification_id.name or '')[:8]
        self.det.prod.EXTIPI.valor = ''
        self.det.prod.CFOP.valor = inv_line.cfop_id.code
        self.det.prod.uCom.valor = inv_line.uos_id.name or ''
        self.det.prod.qCom.valor = str("%.4f" % inv_line.quantity)
        self.det.prod.vUnCom.valor = str("%.7f" % (inv_line.price_unit))
        self.det.prod.vProd.valor = str("%.2f" % inv_line.price_gross)
        self.det.prod.cEANTrib.valor = inv_line.product_id.ean13 or ''
        self.det.prod.uTrib.valor = self.det.prod.uCom.valor
        self.det.prod.qTrib.valor = self.det.prod.qCom.valor
        self.det.prod.vUnTrib.valor = self.det.prod.vUnCom.valor
        self.det.prod.vFrete.valor = str("%.2f" % inv_line.freight_value)
        self.det.prod.vSeg.valor = str("%.2f" % inv_line.insurance_value)
        self.det.prod.vDesc.valor = str("%.2f" % inv_line.discount_value)
        self.det.prod.vOutro.valor = str("%.2f" % inv_line.other_costs_value)
        #
        # Produto entra no total da NF-e
        #
        self.det.prod.indTot.valor = 1

        if inv_line.product_type == 'product':
            #
            # Impostos
            #
            # ICMS
            if inv_line.icms_cst_id.code > 100:
                self.det.imposto.ICMS.CSOSN.valor = inv_line.icms_cst_id.code
                self.det.imposto.ICMS.pCredSN.valor = str("%.2f" % inv_line.icms_percent)
                self.det.imposto.ICMS.vCredICMSSN.valor = str("%.2f" % inv_line.icms_value)

            self.det.imposto.ICMS.CST.valor = inv_line.icms_cst_id.code
            self.det.imposto.ICMS.modBC.valor = inv_line.icms_base_type
            self.det.imposto.ICMS.vBC.valor = str("%.2f" % inv_line.icms_base)
            self.det.imposto.ICMS.pRedBC.valor = str("%.2f" % inv_line.icms_percent_reduction)
            self.det.imposto.ICMS.pICMS.valor = str("%.2f" % inv_line.icms_percent)
            self.det.imposto.ICMS.vICMS.valor = str("%.2f" % inv_line.icms_value)

            # ICMS ST
            self.det.imposto.ICMS.modBCST.valor = inv_line.icms_st_base_type
            self.det.imposto.ICMS.pMVAST.valor = str("%.2f" % inv_line.icms_st_mva)
            self.det.imposto.ICMS.pRedBCST.valor = str("%.2f" % inv_line.icms_st_percent_reduction)
            self.det.imposto.ICMS.vBCST.valor = str("%.2f" % inv_line.icms_st_base)
            self.det.imposto.ICMS.pICMSST.valor = str("%.2f" % inv_line.icms_st_percent)
            self.det.imposto.ICMS.vICMSST.valor = str("%.2f" % inv_line.icms_st_value)

            # IPI
            self.det.imposto.IPI.CST.valor = inv_line.ipi_cst_id.code
            if inv_line.ipi_type == 'percent' or '':
                self.det.imposto.IPI.vBC.valor = str("%.2f" % inv_line.ipi_base)
                self.det.imposto.IPI.pIPI.valor = str("%.2f" % inv_line.ipi_percent)
            if inv_line.ipi_type == 'quantity':
                pesol = 0
                if inv_line.product_id:
                    pesol = inv_line.product_id.weight_net
                    self.det.imposto.IPI.qUnid.valor = str("%.2f" % inv_line.quantity * pesol)
                    self.det.imposto.IPI.vUnid.valor = str("%.2f" % inv_line.ipi_percent)
            self.det.imposto.IPI.vIPI.valor = str("%.2f" % inv_line.ipi_value)

        else:
            #ISSQN
            self.det.imposto.ISSQN.vBC.valor = str("%.2f" % inv_line.issqn_base)
            self.det.imposto.ISSQN.vAliq.valor = str("%.2f" % inv_line.issqn_percent)
            self.det.imposto.ISSQN.vISSQN.valor = str("%.2f" % inv_line.issqn_value)
            self.det.imposto.ISSQN.cMunFG.valor = ('%s%s') % (inv.partner_id.state_id.ibge_code, inv.partner_id.l10n_br_city_id.ibge_code)
            self.det.imposto.ISSQN.cListServ.valor = inv_line.service_type_id.code or ''
            self.det.imposto.ISSQN.cSitTrib.valor = inv_line.issqn_type


        # PIS
        self.det.imposto.PIS.CST.valor = inv_line.pis_cst_id.code
        self.det.imposto.PIS.vBC.valor = str("%.2f" % inv_line.pis_base)
        self.det.imposto.PIS.pPIS.valor = str("%.2f" % inv_line.pis_percent)
        self.det.imposto.PIS.vPIS.valor = str("%.2f" % inv_line.pis_value)

        # PISST
        self.det.imposto.PISST.vBC.valor = str("%.2f" % inv_line.pis_st_base)
        self.det.imposto.PISST.pPIS.valor = str("%.2f" % inv_line.pis_st_percent)
        self.det.imposto.PISST.qBCProd.valor = ''
        self.det.imposto.PISST.vAliqProd.valor = ''
        self.det.imposto.PISST.vPIS.valor = str("%.2f" % inv_line.pis_st_value)

        # COFINS
        self.det.imposto.COFINS.CST.valor = inv_line.cofins_cst_id.code
        self.det.imposto.COFINS.vBC.valor = str("%.2f" % inv_line.cofins_base)
        self.det.imposto.COFINS.pCOFINS.valor = str("%.2f" % inv_line.cofins_percent)
        self.det.imposto.COFINS.vCOFINS.valor = str("%.2f" % inv_line.cofins_value)

        # COFINSST
        self.det.imposto.COFINSST.vBC.valor = str("%.2f" % inv_line.cofins_st_base)
        self.det.imposto.COFINSST.pCOFINS.valor = str("%.2f" % inv_line.cofins_st_percent)
        self.det.imposto.COFINSST.qBCProd.valor = ''
        self.det.imposto.COFINSST.vAliqProd.valor = ''
        self.det.imposto.COFINSST.vCOFINS.valor = str("%.2f" % inv_line.cofins_st_value)

    def _get_details(self, cr, uid, pool, context=None):
        #
        # Detalhes
        #
        # Importamos dados da invoice line
        inv_line = {}

        product_ids = pool.get('product.product').search(
            cr, uid, [('default_code', '=', self.det.prod.cProd.valor)])
        if len(product_ids) == 0:
            cnpj_cpf = self._mask_cnpj_cpf(True, self.nfe.infNFe.emit.CNPJ.valor)
            supplierinfo_ids = pool.get('product.supplierinfo').search(
                        cr, uid, ['|',('name.cnpj_cpf', '=', cnpj_cpf),
                                ('name.cnpj_cpf', '=', self.nfe.infNFe.emit.CNPJ.valor), 
                                ('product_code', '=', self.det.prod.cProd.valor)])
            if len(supplierinfo_ids) > 0:
                supplier_info = pool.get('product.supplierinfo').browse(cr, uid, supplierinfo_ids[0])
                inv_line['product_id'] = supplier_info.product_tmpl_id.id
                inv_line['name'] = supplier_info.product_tmpl_id.name
            else:
                inv_line['product_id'] = False
                inv_line['name'] = ''
        else:
            inv_line['product_id'] = product_ids[0] if product_ids else False
            inv_line['name'] = product_ids[0].name

        
        ncm = self.det.prod.NCM.valor
        ncm = ncm[:4] + '.' + ncm[4:6] + '.' + ncm[6:]
        fc_id = pool.get('account.product.fiscal.classification').search(
             cr, uid, [('name', '=', ncm)]
        )

        inv_line['fiscal_classification_id'] = fc_id[0] if len(fc_id) > 0 else False 

        cfop_ids = pool.get('l10n_br_account_product.cfop').search(
            cr, uid, [('code', '=', self.det.prod.CFOP.valor)])

        inv_line['cfop_id'] = cfop_ids[0] if len(cfop_ids) > 0 else False

        uom_ids = pool.get('product.uom').search(
            cr, uid, [('name', '=like', self.det.prod.uCom.valor)])

        inv_line['uos_id'] = uom_ids[0] if len(uom_ids)> 0 else False
        inv_line['quantity'] = float(self.det.prod.qCom.valor)
        inv_line['price_unit'] = float(self.det.prod.vUnCom.valor)
        inv_line['price_gross'] = float(self.det.prod.vProd.valor)

        inv_line['freight_value'] = float(self.det.prod.vFrete.valor)
        inv_line['insurance_value'] = float(self.det.prod.vSeg.valor)
        inv_line['discount_value'] = float(self.det.prod.vDesc.valor)
        inv_line['other_costs_value'] = float(self.det.prod.vOutro.valor)

        if self.det.imposto.ICMS.orig.valor: #FIXME Corrigir isto
            inv_line['icms_origin'] = str(self.det.imposto.ICMS.orig.valor)

            icms_cst_ids = pool.get('account.tax.code').search(
                cr, uid, [('code', '=', self.det.imposto.ICMS.CST.valor),
                          ('domain', '=', 'icms')])

            inv_line['icms_cst_id'] = icms_cst_ids[0] if icms_cst_ids else False
            inv_line['icms_percent'] = self.det.imposto.ICMS.pCredSN.valor
            inv_line['icms_value'] = self.det.imposto.ICMS.vCredICMSSN.valor

            inv_line['icms_base_type'] = str(self.det.imposto.ICMS.modBC.valor)
            inv_line['icms_base'] = self.det.imposto.ICMS.vBC.valor
            inv_line['icms_percent_reduction'] = self.det.imposto.ICMS.pRedBC.valor
            inv_line['icms_percent'] = self.det.imposto.ICMS.pICMS.valor
            inv_line['icms_value'] = self.det.imposto.ICMS.vICMS.valor

            #
            # # ICMS ST
            #
            inv_line['icms_st_base_type'] = str(self.det.imposto.ICMS.modBCST.valor)
            inv_line['icms_st_mva'] = self.det.imposto.ICMS.pMVAST.valor
            inv_line['icms_st_percent_reduction'] = self.det.imposto.ICMS.pRedBCST.valor
            inv_line['icms_st_base'] = self.det.imposto.ICMS.vBCST.valor
            inv_line['icms_st_percent'] = self.det.imposto.ICMS.pICMSST.valor
            inv_line['icms_st_value'] = self.det.imposto.ICMS.vICMSST.valor

            #
            # # IPI
            #
            ipi_cst_ids = pool.get('account.tax.code').search(
                cr, uid, [('code', '=', self.det.imposto.IPI.CST.valor),
                          ('domain', '=', 'ipi')])
            if self.det.imposto.IPI.vBC.valor and self.det.imposto.IPI.pIPI.valor:
                inv_line['ipi_type'] = 'percent'
                inv_line['ipi_base'] = self.det.imposto.IPI.vBC.valor
                inv_line['ipi_percent'] = self.det.imposto.IPI.pIPI.valor
                inv_line['ipi_cst_id'] = ipi_cst_ids[0] if ipi_cst_ids else False

            elif self.det.imposto.IPI.qUnid.valor and \
                    self.det.imposto.IPI.vUnid.valor:
                inv_line['ipi_percent'] = self.det.imposto.IPI.vUnid.valor

            inv_line['ipi_value'] = self.det.imposto.IPI.vIPI.valor

        else:
            #
            # # ISSQN
            #
            inv_line['issqn_base'] = self.det.imposto.ISSQN.vBC.valor
            inv_line['issqn_percent'] = self.det.imposto.ISSQN.vAliq.valor
            inv_line['issqn_value'] = self.det.imposto.ISSQN.vISSQN.valor
            inv_line['issqn_type'] = self.det.imposto.ISSQN.cSitTrib.valor

        # PIS
        pis_cst_ids = pool.get('account.tax.code').search(
            cr, uid, [('code', '=', self.det.imposto.PIS.CST.valor),('domain', '=', 'pis')])

        inv_line['pis_cst_id'] = pis_cst_ids[0] if pis_cst_ids else False
        inv_line['pis_base'] = self.det.imposto.PIS.vBC.valor
        inv_line['pis_percent'] = self.det.imposto.PIS.pPIS.valor
        inv_line['pis_value'] = self.det.imposto.PIS.vPIS.valor

        # PISST
        inv_line['pis_st_base'] = self.det.imposto.PISST.vBC.valor
        inv_line['pis_st_percent'] = self.det.imposto.PISST.pPIS.valor
        inv_line['pis_st_value'] = self.det.imposto.PISST.vPIS.valor

        # COFINS
        cofins_cst_ids = pool.get('account.tax.code').search(
            cr, uid, [('code', '=', self.det.imposto.COFINS.CST.valor),('domain', '=', 'cofins')])

        inv_line['cofins_cst_id'] = \
            cofins_cst_ids[0] if cofins_cst_ids else False
        inv_line['cofins_base'] = self.det.imposto.COFINS.vBC.valor
        inv_line['cofins_percent'] = self.det.imposto.COFINS.pCOFINS.valor
        inv_line['cofins_value'] = self.det.imposto.COFINS.vCOFINS.valor

        # COFINSST
        inv_line['cofins_st_base'] = self.det.imposto.COFINSST.vBC.valor
        inv_line['cofins_st_percent'] = self.det.imposto.COFINSST.pCOFINS.valor
        inv_line['cofins_st_value'] = self.det.imposto.COFINSST.vCOFINS.valor

        return [(0, 0, inv_line)]



    def _di(self, cr, uid, ids, inv, inv_line, inv_di, i, context=None):
        self.di.nDI.valor = inv_di.name
        self.di.dDI.valor = inv_di.date_registration or ''
        self.di.xLocDesemb.valor = inv_di.location
        self.di.UFDesemb.valor = inv_di.state_id.code or ''
        self.di.dDesemb.valor = inv_di.date_release or ''
        self.di.cExportador.valor = inv_di.exporting_code
        
    def _get_di(self, cr, uid, pool, i, context=None):

        state_ids = pool.search(
            cr, uid, [('code', '=', self.di.UFDesemb.valor)])

        di = {
            'name': self.di.nDI.valor,
            'date_registration': self.di.dDI.valor,
            'location': self.di.xLocDesemb.valor,
            'state_id': state_ids[0] if state_ids else False,
            # self.di.UFDesemb.valor = inv_di.state_id.code or ''
            'date_release': self.di.dDesemb.valor,
            'exporting_code': self.di.cExportador.valor
        }
        return di

    def _addition(self, cr, uid, ids, inv, inv_line, inv_di, inv_di_line, i, context=None):
        self.di_line.nAdicao.valor = inv_di_line.name
        self.di_line.nSeqAdic.valor = inv_di_line.sequence
        self.di_line.cFabricante.valor = inv_di_line.manufacturer_code
        self.di_line.vDescDI.valor = str("%.2f" % inv_di_line.amount_discount)

    def _get_addition(self, cr, uid, ids, inv, inv_line, inv_di, inv_di_line, i, context=None):
        addition = {
            'name': self.di_line.nAdicao.valor,
            'sequence': self.di_line.nSeqAdic.valor,
            'manufacturer_code': self.di_line.cFabricante.valor,
            'amount_discount': self.di_line.vDescDI.valor
        }
        return addition

    def _encashment_data(self, cr, uid, ids, inv, line, context=None):

        #
        # Dados de Cobrança
        #

        self.dup.nDup.valor = line.name
        self.dup.dVenc.valor = line.date_maturity or inv.date_due or inv.date_invoice
        self.dup.vDup.valor = str("%.2f" % (line.debit or line.credit))

    def _get_encashment_data(self, cr, uid, pool, context=None):

        #
        # Dados de Cobrança
        #

        # Realizamos a busca da move line a partir do nome da mesma
        # account_move_line_ids = pool.get('account.move.line').search(
        #     cr, uid, [('name', '=', self.dup.nDup.valor)])
        #
        # if not account_move_line_ids:
        #     # Se nao encontrarmos a move line, nos devemos cria-la
        #     vals = {
        #         'name': self.dup.nDup.valor,
        #         'date_maturity': self.dup.dVenc.valor,
        #         'debit': self.dup.vDup.valor,
        #         # 'journal_id': 1,
        #     }
        #
        #     # Inserimos em um lista para que account_move_line_ids continue
        #     # representando uma lista
        #     context['journal_id'] = 1
        #     context['period_id'] = 1
        #     account_move_line_ids = [pool.get('account.move.line').create(
        #         cr, uid, vals, context=context)]
        #
        # encashment_data = {
        #     'move_line_receivable_id': account_move_line_ids[0] if
        #     account_move_line_ids else False,
        #     'date_due': self.dup.dVenc.valor,
        # }

        # Nao conseguimos obter todos os campos necessarios para criacao
        # do account.move.line
        encashment_data = {}

        return encashment_data


    def _carrier_data(self, cr, uid, ids, inv, context=None):

        #
        # Dados da Transportadora e veiculo
        #

        self.nfe.infNFe.transp.modFrete.valor = inv.incoterm and inv.incoterm.freight_responsibility or '9'

        if inv.carrier_id:

            if inv.carrier_id.partner_id.is_company:
                self.nfe.infNFe.transp.transporta.CNPJ.valor = \
                    re.sub('[%s]' % re.escape(string.punctuation), '', inv.carrier_id.partner_id.cnpj_cpf or '')
            else:
                self.nfe.infNFe.transp.transporta.CPF.valor = \
                    re.sub('[%s]' % re.escape(string.punctuation), '', inv.carrier_id.partner_id.cnpj_cpf or '')

            self.nfe.infNFe.transp.transporta.xNome.valor = inv.carrier_id.partner_id.legal_name[:60] or ''
            self.nfe.infNFe.transp.transporta.IE.valor = inv.carrier_id.partner_id.inscr_est or ''
            self.nfe.infNFe.transp.transporta.xEnder.valor = inv.carrier_id.partner_id.street or ''
            self.nfe.infNFe.transp.transporta.xMun.valor = inv.carrier_id.partner_id.l10n_br_city_id.name or ''
            self.nfe.infNFe.transp.transporta.UF.valor = inv.carrier_id.partner_id.state_id.code or ''

        if inv.vehicle_id:
            self.nfe.infNFe.transp.veicTransp.placa.valor = inv.vehicle_id.plate or ''
            self.nfe.infNFe.transp.veicTransp.UF.valor = inv.vehicle_id.plate.state_id.code or ''
            self.nfe.infNFe.transp.veicTransp.RNTC.valor = inv.vehicle_id.rntc_code or ''

    def _get_carrier_data(self, cr, uid, pool, context=None):

        res = {}

        cnpj_cpf = ''

        # Realizamos a importacao da transportadora
        if self.nfe.infNFe.transp.transporta.CNPJ.valor:
            cnpj_cpf = self.nfe.infNFe.transp.transporta.CNPJ.valor
            cnpj_cpf = self._mask_cnpj_cpf(True, cnpj_cpf)

        elif self.nfe.infNFe.transp.transporta.CPF.valor:
            cnpj_cpf = self.nfe.infNFe.transp.transporta.CPF.valor
            cnpj_cpf = self._mask_cnpj_cpf(False, cnpj_cpf)

        carrier_ids = pool.get('delivery.carrier').search(
            cr, uid, [('partner_id.cnpj_cpf', '=', cnpj_cpf)])

        # Realizamos a busca do veiculo pelo numero da placa
        placa = self.nfe.infNFe.transp.veicTransp.placa.valor

        vehicle_ids = pool.get('l10n_br_delivery.carrier.vehicle').search(
            cr, uid, [('plate', '=', placa)])

        # Ao encontrarmos o carrier com o partner especificado, basta
        # retornarmos seu id que o restantes dos dados vem junto
        res['carrier_id'] = carrier_ids[0] if carrier_ids else False
        res['vehicle_id'] = vehicle_ids[0] if vehicle_ids else False
        
        res['carrier_name'] = self.nfe.infNFe.transp.transporta.xNome.valor
        res['vehicle_plate'] = self.nfe.infNFe.transp.veicTransp.placa.valor
        
        states = pool.get('res.country.state').search(
            cr, uid, [('code', '=', self.nfe.infNFe.transp.veicTransp.UF.valor),
                      ('country_id', '=', 32)])
        res['vehicle_state_id'] = states[0] if states else False        
        return res


    def _weight_data(self, cr, uid, ids, inv, context=None):
        #
        # Campos do Transporte da NF-e Bloco 381
        #
        self.vol.qVol.valor = inv.number_of_packages
        self.vol.esp.valor = inv.kind_of_packages or ''
        self.vol.marca.valor = inv.brand_of_packages or ''
        self.vol.nVol.valor = inv.notation_of_packages or ''
        self.vol.pesoL.valor = str("%.2f" % inv.weight)
        self.vol.pesoB.valor = str("%.2f" % inv.weight_net)

    def _get_weight_data(self, cr, uid, pool, context=None):
        #
        # Campos do Transporte da NF-e Bloco 381
        #
        if len(self.nfe.infNFe.transp.vol) > 0:
            weight_data = {                       
                'number_of_packages': self.nfe.infNFe.transp.vol[0].qVol.valor,
                'kind_of_packages': self.nfe.infNFe.transp.vol[0].esp.valor,
                'brand_of_packages': self.nfe.infNFe.transp.vol[0].marca.valor,
                'notation_of_packages': self.nfe.infNFe.transp.vol[0].nVol.valor,
                'weight': self.nfe.infNFe.transp.vol[0].pesoL.valor,
                'weight_net': self.nfe.infNFe.transp.vol[0].pesoB.valor
            }
            return weight_data
        return {}

    def _additional_information(self, cr, uid, ids, inv, context=None):

        #
        # Informações adicionais
        #
        self.nfe.infNFe.infAdic.infAdFisco.valor = inv.fiscal_comment or ''
        self.nfe.infNFe.infAdic.infCpl.valor = inv.comment or ''

    def _get_additional_information(self, cr, uid, pool, context=None):

        #
        # Informações adicionais
        #
        additional_information = {
            'fiscal_comment': self.nfe.infNFe.infAdic.infAdFisco.valor,
            'comment': self.nfe.infNFe.infAdic.infCpl.valor
        }
        return additional_information


    def _total(self, cr, uid, ids, inv, context=None):

        #
        # Totais
        #
        self.nfe.infNFe.total.ICMSTot.vBC.valor = str("%.2f" % inv.icms_base)
        self.nfe.infNFe.total.ICMSTot.vICMS.valor = str("%.2f" % inv.icms_value)
        self.nfe.infNFe.total.ICMSTot.vBCST.valor = str("%.2f" % inv.icms_st_base)
        self.nfe.infNFe.total.ICMSTot.vST.valor = str("%.2f" % inv.icms_st_value)
        self.nfe.infNFe.total.ICMSTot.vProd.valor = str("%.2f" % inv.amount_gross)
        self.nfe.infNFe.total.ICMSTot.vFrete.valor = str("%.2f" % inv.amount_freight)
        self.nfe.infNFe.total.ICMSTot.vSeg.valor = str("%.2f" % inv.amount_insurance)
        self.nfe.infNFe.total.ICMSTot.vDesc.valor = str("%.2f" % inv.amount_discount)
        self.nfe.infNFe.total.ICMSTot.vII.valor = str("%.2f" % inv.ii_value)
        self.nfe.infNFe.total.ICMSTot.vIPI.valor = str("%.2f" % inv.ipi_value)
        self.nfe.infNFe.total.ICMSTot.vPIS.valor = str("%.2f" % inv.pis_value)
        self.nfe.infNFe.total.ICMSTot.vCOFINS.valor = str("%.2f" % inv.cofins_value)
        self.nfe.infNFe.total.ICMSTot.vOutro.valor = str("%.2f" % inv.amount_costs)
        self.nfe.infNFe.total.ICMSTot.vNF.valor = str("%.2f" % inv.amount_total)

    def _get_total(self, cr, uid, context=None):
        #
        # Totais
        #
        total = {
            'icms_base': self.nfe.infNFe.total.ICMSTot.vBC.valor,
            'icms_value': self.nfe.infNFe.total.ICMSTot.vICMS.valor,
            'icms_st_base': self.nfe.infNFe.total.ICMSTot.vBCST.valor,
            'icms_st_value': self.nfe.infNFe.total.ICMSTot.vST.valor,
            'amount_gross': self.nfe.infNFe.total.ICMSTot.vProd.valor,
            'amount_freight': self.nfe.infNFe.total.ICMSTot.vFrete.valor,
            'amount_insurance': self.nfe.infNFe.total.ICMSTot.vSeg.valor,
            'amount_discount': self.nfe.infNFe.total.ICMSTot.vDesc.valor,
            'ii_value': self.nfe.infNFe.total.ICMSTot.vII.valor,
            'ipi_value': self.nfe.infNFe.total.ICMSTot.vIPI.valor,
            'pis_value': self.nfe.infNFe.total.ICMSTot.vPIS.valor,
            'cofins_value': self.nfe.infNFe.total.ICMSTot.vCOFINS.valor,
            'amount_costs': self.nfe.infNFe.total.ICMSTot.vOutro.valor,
            'amount_total': self.nfe.infNFe.total.ICMSTot.vNF.valor,
        }
        return total

    def _get_protocol(self, cr, uid, pool, context=None):
        protocol = {
            'nfe_status': self.protNFe.infProt.cStat.valor + ' - ' + self.protNFe.infProt.xMotivo.valor,
            'nfe_protocol_number': self.protNFe.infProt.nProt.valor,
            'nfe_date': self.protNFe.infProt.dhRecbto.valor,            
        }
        return protocol

    def get_NFe(self):

        try:
            from pysped.nfe.leiaute import NFe_200
        except ImportError:
            raise orm.except_orm(_(u'Erro!'), _(u"Biblioteca PySPED não instalada!"))

        return NFe_200()

    def _get_NFRef(self):

        try:
            from pysped.nfe.leiaute import NFRef_200
        except ImportError:
            raise orm.except_orm(_(u'Erro!'), _(u"Biblioteca PySPED não instalada!"))

        return NFRef_200()

    def _get_Det(self):

        try:
            from pysped.nfe.leiaute import Det_200
        except ImportError:
            raise orm.except_orm(_(u'Erro!'), _(u"Biblioteca PySPED não instalada!"))

        return Det_200()

    def _get_DI(self):
        try:
            from pysped.nfe.leiaute import DI_200
        except ImportError:
            raise orm.except_orm(_(u'Erro!'), _(u"Biblioteca PySPED não instalada!"))
        return DI_200()

    def _get_Addition(self):
        try:
            from pysped.nfe.leiaute import Adi_200
        except ImportError:
            raise orm.except_orm(_(u'Erro!'), _(u"Biblioteca PySPED não instalada!"))
        return Adi_200()


    def _get_Vol(self):
        try:
            from pysped.nfe.leiaute import Vol_200
        except ImportError:
            raise orm.except_orm(_(u'Erro!'), _(u"Biblioteca PySPED não instalada!"))
        return Vol_200()

    def _get_Dup(self):

        try:
            from pysped.nfe.leiaute import Dup_200
        except ImportError:
            raise orm.except_orm(_(u'Erro!'), _(u"Biblioteca PySPED não instalada!"))

        return Dup_200()

    def get_xml(self, cr, uid, ids, nfe_environment, context=None):
        """"""
        result = []
        for nfe in self._serializer(cr, uid, ids, nfe_environment, context):
            result.append({'key': nfe.infNFe.Id.valor, 'nfe': nfe.get_xml()})
        return result

    def set_xml(self, nfe_string, context=None):
        """"""
        nfe = self.get_NFe()        
        nfe.set_xml(nfe_string)
        return nfe

    def set_txt(self, nfe_string, context=None):
        """"""
        raise orm.except_orm(_(u'Erro!'), _(u"Biblioteca PySPED não "
                                            u"suporta a importaçao "
                                            u"de TXT"))
        #nfe = self.get_NFe()
        #nfe.set_txt(nfe_string)
        #return nfe
        
    def parse_edoc(self, filebuffer, ftype):

        import base64
        filebuffer = base64.standard_b64decode(filebuffer)
        edoc_file = tempfile.NamedTemporaryFile()
        edoc_file.write(filebuffer)
        edoc_file.flush()
        edocs = []
        if ftype == '.zip':
            raise orm.except_orm(_(u'Erro!'), _(u"Importação de zip em "
                                                u"desenvolvimento"))
            #TODO: Unzip and return a list of edoc
        elif ftype == '.xml':
            edocs.append(self.set_xml(edoc_file.name))
        elif ftype == '.txt':
            edocs.append(self.set_txt(edoc_file.name))
        return edocs

    def import_edoc(self, cr, uid, filebuffer, ftype, context):

        edocs = self.parse_edoc(filebuffer, ftype)
        result = []
        for edoc in edocs:
            docid, docaction = self._deserializer(cr, uid, edoc, context)
            result.append({
                'values': docid,
                'action': docaction
            })
        return result

    @staticmethod
    def _mask_cnpj_cpf(is_company, cnpj_cpf):

        if cnpj_cpf:
            val = re.sub('[^0-9]', '', cnpj_cpf)

            if is_company and len(val) == 14:
                cnpj_cpf = "%s.%s.%s/%s-%s" % (val[0:2], val[2:5], val[5:8],
                                               val[8:12], val[12:14])
            elif not is_company and len(val) == 11:
                cnpj_cpf = "%s.%s.%s-%s" % (val[0:3], val[3:6], val[6:9],
                                            val[9:11])

        return cnpj_cpf


class NFe310(NFe200):

    def __init__(self):
        super(NFe310, self).__init__()


    def _nfe_identification(self, cr, uid, ids, inv, company, nfe_environment, context=None):

        super(NFe310, self)._nfe_identification(
            cr, uid, ids, inv, company, nfe_environment, context)

        self.nfe.infNFe.ide.idDest.valor = inv.fiscal_position.id_dest or ''
        self.nfe.infNFe.ide.indFinal.valor = inv.ind_final or ''
        self.nfe.infNFe.ide.indPres.valor = inv.ind_pres or ''
        self.nfe.infNFe.ide.dhEmi.valor = datetime.strptime(inv.date_hour_invoice, '%Y-%m-%d %H:%M:%S')
        self.nfe.infNFe.ide.dhSaiEnt.valor = datetime.strptime(inv.date_in_out, '%Y-%m-%d %H:%M:%S')
        self.nfe.infNFe.ide.hSaiEnt.valor = datetime.strptime(inv.date_in_out, '%Y-%m-%d %H:%M:%S')
        #
        # self.nfe.infNFe.ide.hSaiEnt.valor = datetime.strptime(
        #     inv.date_in_out[-8:], '%H:%M:%S')

    def _get_nfe_identification(self, cr, uid, pool, context=None):

        res = super(NFe310, self)._get_nfe_identification(
            cr, uid, pool, context)

        res['ind_final'] = self.nfe.infNFe.ide.indFinal.valor
        res['ind_pres'] = self.nfe.infNFe.ide.indPres.valor
        res['date_hour_invoice'] = self.nfe.infNFe.ide.dhEmi.valor
        res['date_in_out'] = self.nfe.infNFe.ide.dhSaiEnt.valor
        # TODO: Encontrar uma maneira de importar a posicao fiscal
        # self.nfe.infNFe.ide.idDest.valor = inv.fiscal_position.id_dest or ''

        return res


    def get_NFe(self):

        try:
            from pysped.nfe.leiaute import NFe_310
        except ImportError:
            raise orm.except_orm(_(u'Erro!'), _(u"Biblioteca PySPED não instalada!"))

        return NFe_310()

    def _get_NFRef(self):

        try:
            from pysped.nfe.leiaute import NFRef_310
        except ImportError:
            raise orm.except_orm(_(u'Erro!'), _(u"Biblioteca PySPED não instalada!"))

        return NFRef_310()

    def _get_Det(self):

        try:
            from pysped.nfe.leiaute import Det_310
        except ImportError:
            raise orm.except_orm(_(u'Erro!'), _(u"Biblioteca PySPED não instalada!"))

        return Det_310()

    def _get_Dup(self):

        try:
            from pysped.nfe.leiaute import Dup_310
        except ImportError:
            raise orm.except_orm(_(u'Erro!'), _(u"Biblioteca PySPED não instalada!"))

        return Dup_310()
