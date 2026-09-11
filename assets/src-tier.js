/* 引源分级 · 浏览器端实现（与 sources_tier.py 同口径，改一处要同步改另一处）
 *
 * 站点硬规则：立法 / 标准发布生效 / 合规专项行动 / 监管处罚案例，
 * 必须引用官方账号原文（official）；合规资讯可引官方媒体（gov-media）
 * 与官方学术机构、协会组织（academic）。二手转载（other）不可作为依据。
 */
(function () {
  var LABEL = {
    official: '官方原文',
    'gov-media': '官方媒体',
    academic: '专业机构',
    other: '二手转载'
  };
  var CLASS = {
    official: 'src-off',
    'gov-media': 'src-media',
    academic: 'src-aca',
    other: 'src-oth'
  };

  var OFFICIAL_HOSTS = [
    'npc.gov.cn', 'flk.npc.gov.cn', 'cac.gov.cn', 'beian.cac.gov.cn', '12377.cn',
    'miit.gov.cn', 'samr.gov.cn', 'openstd.samr.gov.cn', 'mohrss.gov.cn',
    'nhc.gov.cn', 'zwfw.nhc.gov.cn', 'mofcom.gov.cn', 'trb.mofcom.gov.cn',
    'court.gov.cn', 'spp.gov.cn', 'mps.gov.cn', 'moj.gov.cn', 'ndrc.gov.cn',
    'mof.gov.cn', 'mot.gov.cn', 'moa.gov.cn', 'most.gov.cn', 'customs.gov.cn',
    'nea.gov.cn', 'nmpa.gov.cn', 'stats.gov.cn', 'sasac.gov.cn', 'gov.cn',
    'ec.europa.eu', 'digital-strategy.ec.europa.eu', 'eur-lex.europa.eu',
    'edpb.europa.eu', 'europa.eu', 'ftc.gov', 'oag.ca.gov', 'ico.org.uk',
    'pdpc.gov.sg', 'meity.gov.in', 'gov.br', 'oecd.org', 'un.org', 'unesco.org'
  ];
  var MEDIA_HOSTS = [
    'people.com.cn', 'cpc.people.com.cn', 'xinhuanet.com', 'news.cn', 'cctv.com',
    'cnr.cn', 'gmw.cn', 'chinanews.com.cn', 'ce.cn', 'china.com.cn',
    'qstheory.cn', 'stdaily.com', 'thepaper.cn', 'jfdaily.com'
  ];
  var ACADEMIC_HOSTS = [
    'caict.ac.cn', 'tc260.org.cn', 'cnis.ac.cn', 'sacinfo.org.cn', 'isc.org.cn',
    'cybersac.cn', 'cca.org.cn', 'chinawuliu.com.cn', 'ccas.com.cn',
    'chinacpi.org', 'cagp.org.cn', 'ssrn.com', 'arxiv.org', 'papers.ssrn.com'
  ];

  function hostOf(url) {
    try {
      return new URL(url, location.href).hostname.toLowerCase().replace(/^www\./, '');
    } catch (e) {
      return '';
    }
  }

  function tierOf(url, declared) {
    var h = hostOf(url);
    if (!h) return declared === 'official' ? 'official' : 'other';
    if (OFFICIAL_HOSTS.indexOf(h) >= 0 || MEDIA_HOSTS.indexOf(h) >= 0 ||
        ACADEMIC_HOSTS.indexOf(h) >= 0) {
      if (OFFICIAL_HOSTS.indexOf(h) >= 0) return 'official';
      if (MEDIA_HOSTS.indexOf(h) >= 0) return 'gov-media';
      return 'academic';
    }
    if (/gov\.cn$/.test(h) || /(^|\.)gov(\.[a-z]{2})?$/.test(h) || /europa\.eu$/.test(h) ||
        /\.(go\.jp|go\.kr|gouv\.[a-z]{2}|gob\.[a-z]{2}|gov\.uk|gov\.au|gov\.hk|gov\.mo)$/.test(h)) {
      return 'official';
    }
    if (/(people\.com\.cn|xinhuanet\.com|news\.cn|cctv\.com|gmw\.cn|ce\.cn|thepaper\.cn|cnr\.cn|chinanews\.com\.cn|qstheory\.cn|stdaily\.com)$/.test(h)) {
      return 'gov-media';
    }
    if (/\.(edu\.cn|ac\.cn|edu|ac\.uk|org\.cn)$/.test(h)) return 'academic';
    return 'other';
  }

  function srcTierTag(url, declared) {
    var t = tierOf(url, declared);
    return '<span class="rd-src ' + CLASS[t] + '">' + LABEL[t] + '</span>';
  }

  window.SRC_TIER = { LABEL: LABEL, CLASS: CLASS, tierOf: tierOf, tag: srcTierTag };
  window.srcTierOf = tierOf;
  window.srcTierTag = srcTierTag;
})();
