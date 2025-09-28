#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#ifdef ENABLE_READLINE
#include <readline/readline.h>
#include <readline/history.h>
#endif
#define MAX_RECORDS 1000
#define NAME_LEN 64
#define CAT_LEN 32
#define DATE_LEN 11
#define LINE_LEN 512
#define BIN_FILE "records.bin"
#define JSON_FILE "records.json"
#define CSV_FILE "records.csv"
typedef struct{int id;char name[NAME_LEN];double amount;char category[CAT_LEN];char date[DATE_LEN];}Record;
static Record records[MAX_RECORDS];
static int record_count=0;
static int next_id=1;
static void trim(char*s){size_t n=strlen(s);if(n&&s[n-1]=='\n')s[n-1]=0;}
int find_index_by_id(int id){for(int i=0;i<record_count;i++)if(records[i].id==id)return i;return -1;}
void add_record(const char*n,double a,const char*c,const char*d){if(record_count>=MAX_RECORDS){puts("Full");return;}records[record_count].id=next_id++;strncpy(records[record_count].name,n,NAME_LEN-1);records[record_count].name[NAME_LEN-1]=0;records[record_count].amount=a;strncpy(records[record_count].category,c,CAT_LEN-1);records[record_count].category[CAT_LEN-1]=0;strncpy(records[record_count].date,d,DATE_LEN-1);records[record_count].date[DATE_LEN-1]=0;record_count++;puts("Added");}
int delete_record(int id){int idx=find_index_by_id(id);if(idx<0)return 0;for(int i=idx;i<record_count-1;i++)records[i]=records[i+1];record_count--;return 1;}
int update_record(int id,const char*n,double a,const char*c,const char*d){int idx=find_index_by_id(id);if(idx<0)return 0;strncpy(records[idx].name,n,NAME_LEN-1);records[idx].name[NAME_LEN-1]=0;records[idx].amount=a;strncpy(records[idx].category,c,CAT_LEN-1);records[idx].category[CAT_LEN-1]=0;strncpy(records[idx].date,d,DATE_LEN-1);records[idx].date[DATE_LEN-1]=0;return 1;}
void swap_rec(int i,int j){Record t=records[i];records[i]=records[j];records[j]=t;}
void sort_by_amount_desc(void){for(int i=0;i<record_count-1;i++)for(int j=i+1;j<record_count;j++)if(records[i].amount<records[j].amount)swap_rec(i,j);}
void sort_by_id_asc(void){for(int i=0;i<record_count-1;i++)for(int j=i+1;j<record_count;j++)if(records[i].id>records[j].id)swap_rec(i,j);}
void list_records(const char*mode,const char*cat,const char*from,const char*to){
 if(record_count==0){puts("No records");return;}
 Record backup[MAX_RECORDS];memcpy(backup,records,sizeof(Record)*record_count);
 if(!mode||strcmp(mode,"amount")==0)sort_by_amount_desc();else if(strcmp(mode,"id")==0)sort_by_id_asc();
 double total=0;int cnt=0;
 for(int i=0;i<record_count;i++){
  int ok=1;
  if(cat&&cat[0])if(strcmp(records[i].category,cat))ok=0;
  if(from&&from[0]&&strcmp(records[i].date,"")!=0)if(strcmp(records[i].date,from)<0)ok=0;
  if(to&&to[0]&&strcmp(records[i].date,"")!=0)if(strcmp(records[i].date,to)>0)ok=0;
  if(!ok)continue;
  printf("%d %s %.2f %s %s\n",records[i].id,records[i].name,records[i].amount,records[i].category,records[i].date);
  total+=records[i].amount;cnt++;
 }
 if(cnt)printf("Count:%d Total:%.2f Avg:%.2f\n",cnt,total,total/cnt);else puts("No matched records");
 memcpy(records,backup,sizeof(Record)*record_count);
}
int save_bin(const char*fn){
 FILE*f=fopen(fn,"wb");if(!f)return 0;fwrite(&record_count,sizeof(record_count),1,f);fwrite(&next_id,sizeof(next_id),1,f);for(int i=0;i<record_count;i++)fwrite(&records[i],sizeof(Record),1,f);fclose(f);return 1;}
int load_bin(const char*fn){
 FILE*f=fopen(fn,"rb");if(!f)return 0;int rc=0;int nid=1;fread(&rc,sizeof(rc),1,f);fread(&nid,sizeof(nid),1,f);if(rc<0||rc>MAX_RECORDS){fclose(f);return 0;}record_count=rc;next_id=nid;for(int i=0;i<record_count;i++)fread(&records[i],sizeof(Record),1,f);fclose(f);return 1;}
int save_json(const char*fn){
 FILE*f=fopen(fn,"w");if(!f)return 0;fprintf(f,"[");for(int i=0;i<record_count;i++){char escname[NAME_LEN*2];char esccat[CAT_LEN*2];int p=0;for(char*s=records[i].name;*s&&p<sizeof(escname)-2;s++){if(*s=='\"'||*s=='\\'){escname[p++]='\\';escname[p++]=*s;}else if(*s=='\n'){escname[p++]='\\';escname[p++]='n';}else escname[p++]=*s;}escname[p]=0;p=0;for(char*s=records[i].category;*s&&p<sizeof(esccat)-2;s++){if(*s=='\"'||*s=='\\'){esccat[p++]='\\';esccat[p++]=*s;}else esccat[p++]=*s;}esccat[p]=0;fprintf(f,"{\"id\":%d,\"name\":\"%s\",\"amount\":%.10g,\"category\":\"%s\",\"date\":\"%s\"}%s",records[i].id,escname,records[i].amount,esccat,records[i].date,i==record_count-1?"":",");}fprintf(f,"]");fclose(f);return 1;}
int load_json(const char*fn){
 FILE*f=fopen(fn,"r");if(!f)return 0;char buf[8192];size_t n=fread(buf,1,sizeof(buf)-1,f);fclose(f);buf[n]=0;record_count=0;next_id=1;char*ptr=buf;while((ptr=strstr(ptr,"{\"id\":"))){int id=0;char name[NAME_LEN]={0};double amt=0;char cat[CAT_LEN]={0};char date[DATE_LEN]={0};if(sscanf(ptr,"{\"id\":%d",&id)==1){char*p1=strstr(ptr,"\"name\":\"");if(p1){p1+=8;char*p2=strchr(p1,'\"');if(p2){int l=p2-p1;if(l>=NAME_LEN)l=NAME_LEN-1;memcpy(name,p1,l);name[l]=0;}}char*p3=strstr(ptr,"\"amount\":");if(p3)sscanf(p3+9,"%lf",&amt);char*p4=strstr(ptr,"\"category\":\"");if(p4){p4+=12;char*p5=strchr(p4,'\"');if(p5){int l=p5-p4;if(l>=CAT_LEN)l=CAT_LEN-1;memcpy(cat,p4,l);cat[l]=0;}}char*p6=strstr(ptr,"\"date\":\"");if(p6){p6+=8;char*p7=strchr(p6,'\"');if(p7){int l=p7-p6;if(l>=DATE_LEN)l=DATE_LEN-1;memcpy(date,p6,l);date[l]=0;}}if(record_count<MAX_RECORDS){records[record_count].id=id;strncpy(records[record_count].name,name,NAME_LEN-1);records[record_count].amount=amt;strncpy(records[record_count].category,cat,CAT_LEN-1);strncpy(records[record_count].date,date,DATE_LEN-1);record_count++;if(id>=next_id)next_id=id+1;}}ptr+=6;}return 1;}
int export_csv(const char*fn){
 FILE*f=fopen(fn,"w");if(!f)return 0;fprintf(f,"id,name,amount,category,date\n");for(int i=0;i<record_count;i++){char n1[NAME_LEN*2];int p=0;for(char*s=records[i].name;*s&&p<sizeof(n1)-1;s++){if(*s==','||*s=='\"'){n1[p++]='\"';n1[p++]=*s;n1[p++]='\"';}else n1[p++]=*s;}n1[p]=0;fprintf(f,"%d,\"%s\",%.2f,\"%s\",\"%s\"\n",records[i].id,records[i].name,records[i].amount,records[i].category,records[i].date);}fclose(f);return 1;}
static void parse_quoted(const char*src,char*out,int outlen,const char**rest){
 while(*src&&isspace((unsigned char)*src))src++;
 if(*src=='\"'){src++;int i=0;while(*src&&*src!='\"'&&i<outlen-1)out[i++]=*src++;out[i]=0;if(*src=='\"')src++;}else{int i=0;while(*src&&!isspace((unsigned char)*src)&&i<outlen-1)out[i++]=*src++;out[i]=0;}
 while(*src&&isspace((unsigned char)*src))src++;
 *rest=src;
}
void print_help(){puts("Commands: add NAME AMOUNT [CATEGORY] [YYYY-MM-DD] | del ID | upd ID NAME AMOUNT [CATEGORY] [YYYY-MM-DD] | list [amount|id|added] [category=C] [from=YYYY-MM-DD] [to=YYYY-MM-DD] | savebin | loadbin | savejson | loadjson | exportcsv | exit");}
int main(void){
 char line[LINE_LEN];
 load_json(JSON_FILE);
 print_help();
 while(1){
#ifdef ENABLE_READLINE
 char*rl=readline("> ");
 if(!rl)break;
 if(*rl) add_history(rl);
 strncpy(line,rl,LINE_LEN-1);line[LINE_LEN-1]=0;free(rl);
#else
 if(!fgets(line,sizeof(line),stdin))break;
 trim(line);
 if(line[0]==0)continue;
#endif
 char cmd[32]={0};const char*ptr=line;int i=0;while(*ptr&&!isspace((unsigned char)*ptr)&&i<(int)sizeof(cmd)-1)cmd[i++]=*ptr++;cmd[i]=0;while(*ptr&&isspace((unsigned char)*ptr))ptr++;
 if(strcmp(cmd,"add")==0){char name[NAME_LEN]={0},cat[CAT_LEN]={0},date[DATE_LEN]={0};const char*rest;parse_quoted(ptr,name,NAME_LEN,&rest);if(name[0]==0){puts("Bad args");continue;}double amt=0;if(*rest)amt=strtod(rest,(char**)&rest);parse_quoted(rest,cat,CAT_LEN,&rest);parse_quoted(rest,date,DATE_LEN,&rest);add_record(name,amt,cat,date);}
 else if(strcmp(cmd,"del")==0){int id=atoi(ptr);if(id==0){puts("Bad args");continue;}if(delete_record(id))puts("Deleted");else puts("Not found");}
 else if(strcmp(cmd,"upd")==0){char idb[32]={0};int j=0;while(*ptr&&!isspace((unsigned char)*ptr)&&j<31)idb[j++]=*ptr++;idb[j]=0;while(*ptr&&isspace((unsigned char)*ptr))ptr++;int id=atoi(idb);if(id==0){puts("Bad args");continue;}char name[NAME_LEN]={0},cat[CAT_LEN]={0},date[DATE_LEN]={0};const char*rest;parse_quoted(ptr,name,NAME_LEN,&rest);if(name[0]==0){puts("Bad args");continue;}double amt=strtod(rest,(char**)&rest);parse_quoted(rest,cat,CAT_LEN,&rest);parse_quoted(rest,date,DATE_LEN,&rest);if(update_record(id,name,amt,cat,date))puts("Updated");else puts("Not found");}
 else if(strcmp(cmd,"list")==0){char mode[16]={0},cat[CAT_LEN]={0},from[DATE_LEN]={0},to[DATE_LEN]={0};const char*rp=ptr;while(*rp){char tok[128]={0};int k=0;while(*rp&&!isspace((unsigned char)*rp)&&k<127)tok[k++]=*rp++;tok[k]=0;while(*rp&&isspace((unsigned char)*rp))rp++;if(strncmp(tok,"category=",9)==0)strncpy(cat,tok+9,CAT_LEN-1);else if(strncmp(tok,"from=",5)==0)strncpy(from,tok+5,DATE_LEN-1);else if(strncmp(tok,"to=",3)==0)strncpy(to,tok+3,DATE_LEN-1);else strncpy(mode,tok,15);}if(mode[0]==0)list_records("amount",cat,from,to);else list_records(mode,cat,from,to);}
 else if(strcmp(cmd,"savebin")==0){if(save_bin(BIN_FILE))puts("Saved bin");else puts("Save failed");}
 else if(strcmp(cmd,"loadbin")==0){if(load_bin(BIN_FILE))puts("Loaded bin");else puts("Load failed");}
 else if(strcmp(cmd,"savejson")==0){if(save_json(JSON_FILE))puts("Saved json");else puts("Save failed");}
 else if(strcmp(cmd,"loadjson")==0){if(load_json(JSON_FILE))puts("Loaded json");else puts("Load failed");}
 else if(strcmp(cmd,"exportcsv")==0){if(export_csv(CSV_FILE))puts("Exported");else puts("Export failed");}
 else if(strcmp(cmd,"exit")==0)break;
 else if(strcmp(cmd,"help")==0)print_help();
 else puts("Unknown");
 }
 return 0;
}
