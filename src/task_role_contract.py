"""Current package role outranks project title/delivery mode. Bounded prose gate."""
import re
from src.company_narrative import outward_fields,_clauses,TRAD

ROLES={
 'supervisor':'监管/监理：独立监督、检查、进度/质量审查与记录；不承担施工总包或整包设计施工责任',
 'designer':'设计：设计统筹、设计成果、顾问接口和复核；不承担整包EPC设计采购施工责任',
 'contractor':'承建商：施工组织、工地管理与常规专业分包，按任务要求承担施工责任',
 'supplier':'供应商：产品/材料供应、配送、文档与保修接口；不自动承担整包施工责任',
}
def role_context(role):
    if role not in ROLES: raise ValueError('Unsupported explicit task role: '+str(role))
    return ('\nCURRENT TASK ROLE CONTRACT (authoritative for this controlled task):\n'
      +role+': '+ROLES[role]+'\n'
      'The historical project title and EPC/DBB delivery label describe the project, not your tender role. '
      'All decisions, reasons and proposals must use the current task role above, including no_bid reasons. '
      'Do not infer company capability from the assigned role. Return task_role:"'+role+'" in final JSON. '
      'Other actors such as a general contractor may be discussed as other parties; do not claim their responsibilities as your own.\n')

class TaskRoleIssue(ValueError):
    category='task_role_conflict'
    retryable=True
    def __init__(self,role,findings):
        self.paths=sorted({f['path'] for f in findings})
        self.report={'status':'blocked','findings':findings}
        super().__init__('Current task role '+role+' conflicts with output: '+str(findings))

def require_task_role(data,role):
    if role not in ROLES: raise ValueError('Unsupported explicit task role')
    findings=[]
    if data.get('task_role')!=role:
        findings.append({'path':'/task_role','category':'task_role_conflict','quote':str(data.get('task_role')),
          'expected':role,'reason':'Use the host task role; it does not establish capability.'})
    if role in {'supervisor','designer'}:
        own=r'(?:我(?:司|方|们)|本公司|公司)'
        for path,text in outward_fields(data):
            for offset,raw in _clauses(text):
                clause=raw.translate(TRAD)
                patterns=[rf'{own}.{{0,18}}(?:作为|担任|担负|承担|以).{{0,20}}(?:总承包商|总承包主体|总承包人|施工总包)',
                  r'(?:投标方|本包).{0,16}(?:须|需要|要求|承担).{0,18}(?:设计与施工|设计、采购和施工|设计采购施工).{0,10}(?:整体|全部|整包)']
                if role=='supervisor':
                    patterns.append(r'(?:方向为|理由是|交付上|拟议安排).{0,20}总承包主体')
                for pattern in patterns:
                    for m in re.finditer(pattern,clause):
                        # Explicitly allocating work to another actor is valid.
                        before=clause[:m.end()]
                        actions=list(re.finditer(r'作为|担任|担负|承担|以',m.group()))
                        prior_action=m.group()[:actions[-1].start()] if actions else before
                        if re.search(r'(?:不|不得|不能|无需|并非)$',prior_action): continue
                        if re.search(r'(?:施工|采购).{0,8}(?:由|属).{0,12}(?:其他|EPC牵头方|总包方)',clause): continue
                        findings.append({'path':path,'category':'task_role_conflict','quote':raw,
                          'expected':role,'reason':'Own/required whole-contractor responsibility contradicts the controlled role.'})
    if findings: raise TaskRoleIssue(role,findings)
    return {'origin':'host_role_contract','task_role':role,'status':'bounded_role_checks_passed',
      'limits':'Enum and explicit own-responsibility conflicts only; implicit role drift still requires common content review.'}
